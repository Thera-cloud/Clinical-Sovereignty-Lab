import 'dart:convert';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import '../config/app_config.dart';
import 'studio_html_media.dart';

const _gold = Color(0xFFC9A962);
const _muted = Color(0xFF8B7355);
const _text = Color(0xFFE8D5A3);
const _void = Color(0xFF050505);
const _chamber = Color(0xFF0A0A0A);
const _elevated = Color(0xFF111111);
const _border = Color(0xFF222222);
const _red = Color(0xFFEF4444);
const _cyan = Color(0xFF4ECDC4);
const _okGreen = Color(0xFF22C55E);

const _slotDefs = <Map<String, Object>>[
  {'id': 1, 'slot': 'intro', 'label': 'Podcast Intro', 'max': 20.0, 'maxLabel': '20s'},
  {'id': 2, 'slot': 'hook', 'label': 'Hook Video', 'max': 30.0, 'maxLabel': '30s'},
  {'id': 3, 'slot': 'topic1', 'label': 'Topic 1', 'max': 330.0, 'maxLabel': '5m 30s'},
  {'id': 4, 'slot': 'commercial', 'label': 'Commercial Plug', 'max': 120.0, 'maxLabel': '2m'},
  {'id': 5, 'slot': 'topic2', 'label': 'Topic 2', 'max': 330.0, 'maxLabel': '5m 30s'},
  {'id': 6, 'slot': 'closing', 'label': 'Closing Plug', 'max': 120.0, 'maxLabel': '2m'},
  {'id': 7, 'slot': 'credential', 'label': 'Credential Video', 'max': 60.0, 'maxLabel': '1m'},
];

class CoachStudioPodcastEditor extends StatefulWidget {
  final String token;
  final Map<String, dynamic> episode;
  final VoidCallback onBack;
  final VoidCallback onRefresh;

  const CoachStudioPodcastEditor({
    super.key,
    required this.token,
    required this.episode,
    required this.onBack,
    required this.onRefresh,
  });

  @override
  State<CoachStudioPodcastEditor> createState() =>
      _CoachStudioPodcastEditorState();
}

class _CoachStudioPodcastEditorState extends State<CoachStudioPodcastEditor> {
  final _handle = StudioMediaHandle();
  List<Map<String, dynamic>> _library = [];
  List<Map<String, dynamic>> _slots = [];
  Map<String, dynamic>? _active;
  Map<String, dynamic>? _bgAudio;
  int _target = 1;
  double _in = 0;
  double _out = 20;
  double _duration = 0;
  double _now = 0;
  bool _busy = false;
  String _status = '';
  String _title = '';

  String get _eid => (widget.episode['id'] ?? '').toString();

  Map<String, String> get _h => {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ${widget.token}',
      };

  @override
  void initState() {
    super.initState();
    _title = (widget.episode['title'] ?? 'Episode').toString();
    _slots = _emptySlots();
    _hydrate(widget.episode);
    _reload();
  }

  List<Map<String, dynamic>> _emptySlots() {
    return _slotDefs
        .map((d) => {
              'id': d['id'],
              'slot': d['slot'],
              'label': d['label'],
              'max_s': d['max'],
              'maxLabel': d['maxLabel'],
              'clip': null,
            })
        .toList();
  }

  void _hydrate(Map<String, dynamic> ep) {
    final board = List<Map<String, dynamic>>.from(
        ((ep['storyboard'] ?? []) as List)
            .map((e) => Map<String, dynamic>.from(e as Map)));
    if (board.length == 7) {
      for (var i = 0; i < 7; i++) {
        board[i]['maxLabel'] = _slotDefs[i]['maxLabel'];
        board[i]['label'] = _slotDefs[i]['label'];
      }
      _slots = board;
    }
    _buildLibrary(
        ep,
        List<Map<String, dynamic>>.from(((ep['assets'] ?? []) as List)
            .map((e) => Map<String, dynamic>.from(e as Map))));
  }

  void _buildLibrary(Map<String, dynamic> ep, List<Map<String, dynamic>> assets) {
    final masterUrl = (ep['master_tape_url'] ?? ep['tape_url'] ?? '').toString();
    final masterKey = (ep['media_master_r2_key'] ?? '').toString();
    final lib = <Map<String, dynamic>>[
      {
        'id': 'master',
        'title': 'Uncut Master Tape',
        'kind': 'master',
        'url': masterUrl,
        'r2_key': masterKey,
        'pinned': true,
        'duration_s': 0.0,
      },
    ];
    for (final a in assets) {
      lib.add({
        'id': (a['id'] ?? '').toString(),
        'title': (a['title'] ?? 'Clip').toString(),
        'kind': (a['kind'] ?? 'video').toString(),
        'url': (a['url'] ?? '').toString(),
        'r2_key': (a['r2_key'] ?? '').toString(),
        'pinned': false,
        'duration_s': (a['duration_s'] as num?)?.toDouble() ?? 0.0,
      });
    }
    _library = lib;
    _active ??= lib.first;
    final url = (_active?['url'] ?? '').toString();
    if (url.isEmpty && masterUrl.isNotEmpty) _active = lib.first;
  }

  Future<void> _reload() async {
    try {
      final r = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/studio/episodes/$_eid'),
        headers: _h,
      );
      if (!mounted || r.statusCode != 200) return;
      final j = json.decode(r.body) as Map<String, dynamic>;
      final ep = Map<String, dynamic>.from((j['episode'] ?? {}) as Map);
      setState(() {
        _title = (ep['title'] ?? _title).toString();
        _hydrate(ep);
      });
    } catch (_) {}
  }

  String _fmt(double s) {
    if (s.isNaN || s.isInfinite || s < 0) s = 0;
    final t = s.floor();
    final m = t ~/ 60;
    final r = t % 60;
    return '${m.toString().padLeft(2, '0')}:${r.toString().padLeft(2, '0')}';
  }

  double _maxFor(int id) {
    final row =
        _slotDefs.firstWhere((d) => d['id'] == id, orElse: () => _slotDefs.first);
    return (row['max'] as double);
  }

  String _maxLabelFor(int id) {
    final row =
        _slotDefs.firstWhere((d) => d['id'] == id, orElse: () => _slotDefs.first);
    return (row['maxLabel'] as String);
  }

  String _slotLabel(int id) {
    final row =
        _slotDefs.firstWhere((d) => d['id'] == id, orElse: () => _slotDefs.first);
    return (row['label'] as String);
  }

  double _stitchSeconds() {
    var t = 0.0;
    for (final s in _slots) {
      final clip = s['clip'];
      if (clip is! Map) continue;
      t += ((clip['end_s'] as num?)?.toDouble() ?? 0) -
          ((clip['start_s'] as num?)?.toDouble() ?? 0);
    }
    return t < 0 ? 0 : t;
  }

  Map<String, dynamic> _payload() {
    return {
      'storyboard': _slots.map((s) {
        final clip = s['clip'];
        if (clip is! Map) {
          return {'id': s['id'], 'slot': s['slot'], 'clip': null};
        }
        return {
          'id': s['id'],
          'slot': s['slot'],
          'clip': {
            'source_id': clip['source_id'],
            'source_title': clip['source_title'],
            'r2_key': clip['r2_key'] ?? '',
            'start_s': clip['start_s'],
            'end_s': clip['end_s'],
            'audio_id': clip['audio_id'] ?? '',
            'audio_r2_key': clip['audio_r2_key'] ?? '',
          },
        };
      }).toList(),
    };
  }

  Future<void> _saveDraft() async {
    try {
      await http.put(
        Uri.parse('${AppConfig.apiBaseUrl}/api/studio/episodes/$_eid/storyboard'),
        headers: _h,
        body: json.encode(_payload()),
      );
    } catch (_) {}
  }

  void _selectMedia(Map<String, dynamic> item) {
    setState(() {
      _active = item;
      _in = 0;
      final cap = _maxFor(_target);
      final dur = (item['duration_s'] as num?)?.toDouble() ?? 0;
      _out = dur > 0 && dur < cap ? dur : cap;
      _now = 0;
      _duration = dur;
    });
    _handle.seek?.call(0);
  }

  Future<void> _upload({int? intoSlot}) async {
    final picked = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: const [
        'mp4',
        'webm',
        'mov',
        'mp3',
        'wav',
        'm4a',
        'aac',
        'ogg'
      ],
      withData: true,
    );
    if (picked == null || picked.files.isEmpty) return;
    final f = picked.files.first;
    final bytes = f.bytes;
    if (bytes == null || bytes.isEmpty) {
      _toast('Could not read file');
      return;
    }
    if (bytes.length > 80 * 1000 * 1000) {
      _toast('File too large (80 MB max)');
      return;
    }
    final ext = (f.extension ?? '').toLowerCase();
    final audio = {'mp3', 'wav', 'm4a', 'aac', 'ogg'}.contains(ext);
    var kind = audio ? 'audio' : 'video';
    if (intoSlot == 4) kind = 'commercial';
    setState(() => _busy = true);
    try {
      final req = http.MultipartRequest(
        'POST',
        Uri.parse('${AppConfig.apiBaseUrl}/api/studio/episodes/$_eid/assets'),
      );
      req.headers['Authorization'] = 'Bearer ${widget.token}';
      req.fields['kind'] = kind;
      req.fields['title'] = f.name;
      req.files.add(http.MultipartFile.fromBytes('file', bytes, filename: f.name));
      final streamed = await req.send();
      final body = await streamed.stream.bytesToString();
      if (streamed.statusCode != 200) {
        _toast('Upload failed (${streamed.statusCode})');
        return;
      }
      final j = json.decode(body) as Map<String, dynamic>;
      final asset = Map<String, dynamic>.from((j['asset'] ?? {}) as Map);
      final item = {
        'id': (asset['id'] ?? '').toString(),
        'title': (asset['title'] ?? f.name).toString(),
        'kind': (asset['kind'] ?? kind).toString(),
        'url': (asset['url'] ?? '').toString(),
        'r2_key': (asset['r2_key'] ?? '').toString(),
        'pinned': false,
        'duration_s': (asset['duration_s'] as num?)?.toDouble() ?? 0.0,
      };
      setState(() {
        _library.add(item);
        _active = item;
      });
      if (intoSlot != null) {
        _assign(intoSlot, item, 0, _maxFor(intoSlot), advance: true);
      }
      _toast('Added to session library');
    } catch (e) {
      _toast('Upload failed: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  bool _assign(
    int slotId,
    Map<String, dynamic> src,
    double start,
    double end, {
    bool advance = false,
    bool notices = true,
  }) {
    final maxS = _maxFor(slotId);
    var a = start < 0 ? 0.0 : start;
    var b = end;
    if (b <= a) {
      if (notices) {
        _notice('Invalid Clip', 'Out point must be greater than In point.');
      }
      return false;
    }
    if (b - a > maxS + 0.08) {
      if (notices) {
        _notice(
          'Time Limit Exceeded',
          'This clip (${_fmt(b - a)}) exceeds the maximum allowed time for ${_slotLabel(slotId)} (${_maxLabelFor(slotId)}).',
        );
      }
      return false;
    }
    final idx = _slots.indexWhere((s) => s['id'] == slotId);
    if (idx < 0) return false;
    setState(() {
      _slots[idx]['clip'] = {
        'source_id': src['id'],
        'source_title': src['title'],
        'r2_key': src['id'] == 'master' ? '' : (src['r2_key'] ?? ''),
        'start_s': a,
        'end_s': b,
        'duration_s': b - a,
        'audio_id': _bgAudio?['id'] ?? '',
        'audio_r2_key': _bgAudio?['r2_key'] ?? '',
      };
      _status = 'Sent to ${_slots[idx]['label']}';
      if (advance) _advanceTarget(slotId);
    });
    _saveDraft();
    return true;
  }

  void _advanceTarget(int fromId) {
    for (final s in _slots) {
      final id = s['id'] as int;
      if (id > fromId && s['clip'] == null) {
        _target = id;
        return;
      }
    }
  }

  void _sendClip() {
    final src = _active;
    if (src == null) {
      _notice('Invalid Clip', 'Select media from the library first.');
      return;
    }
    _assign(_target, src, _in, _out, advance: true);
  }

  void _clearSlot(int id) {
    final idx = _slots.indexWhere((s) => s['id'] == id);
    if (idx < 0) return;
    setState(() => _slots[idx]['clip'] = null);
    _saveDraft();
  }

  List<Map<String, dynamic>> get _filled {
    return _slots.where((s) => s['clip'] is Map).toList();
  }

  Future<void> _previewSlot(Map<String, dynamic> slot) async {
    final clip = slot['clip'];
    if (clip is! Map) return;
    final src = _lookup(clip['source_id']?.toString() ?? 'master');
    final url = (src?['url'] ?? '').toString();
    if (url.isEmpty) {
      _notice('Clip Preview', 'Media missing for this slot.');
      return;
    }
    await showDialog<void>(
      context: context,
      builder: (ctx) => _PreviewShell(
        title: '${slot['id']}. ${slot['label']}',
        isFinal: false,
        child: StudioHtmlMediaPlayer(
          url: url,
          isAudio: (src?['kind'] ?? '') == 'audio',
          loopStart: (clip['start_s'] as num?)?.toDouble(),
          loopEnd: (clip['end_s'] as num?)?.toDouble(),
        ),
      ),
    );
  }

  Map<String, dynamic>? _lookup(String id) {
    for (final m in _library) {
      if ((m['id'] ?? '').toString() == id) return m;
    }
    return _library.isEmpty ? null : _library.first;
  }

  Future<void> _previewStitched() async {
    final clips = _filled;
    if (clips.isEmpty) {
      _notice(
        'Empty Storyboard',
        'Please add at least one clip to the timeline before previewing the final stitch.',
      );
      return;
    }
    await showDialog<void>(
      context: context,
      builder: (ctx) => _StitchPreviewDialog(slots: clips, lookup: _lookup),
    );
  }

  Future<void> _openAdjust(Map<String, dynamic> slot) async {
    final clip = slot['clip'];
    if (clip is! Map) return;
    final src = _lookup(clip['source_id']?.toString() ?? 'master');
    final saved = await showDialog<Map<String, double>>(
      context: context,
      barrierColor: Colors.black.withValues(alpha: 0.8),
      builder: (ctx) => _AdjustPlacedClipDialog(
        slot: slot,
        source: src,
        start: (clip['start_s'] as num?)?.toDouble() ?? 0,
        end: (clip['end_s'] as num?)?.toDouble() ?? 1,
        maxS: (slot['max_s'] as num?)?.toDouble() ?? 20,
        maxLabel: (slot['maxLabel'] ?? _maxLabelFor(slot['id'] as int)).toString(),
        fmt: _fmt,
      ),
    );
    if (saved == null || src == null) return;
    final prevAudio = _bgAudio;
    final audioId = (clip['audio_id'] ?? '').toString();
    if (audioId.isNotEmpty) {
      _bgAudio = {
        'id': audioId,
        'r2_key': clip['audio_r2_key'] ?? '',
      };
    }
    _assign(
      slot['id'] as int,
      src,
      saved['in'] ?? 0,
      saved['out'] ?? 0,
      notices: true,
    );
    _bgAudio = prevAudio;
  }

  Future<void> _approveAndPublish() async {
    if (_filled.isEmpty) {
      _notice(
        'Empty Storyboard',
        'Cannot publish an empty edit. Please add clips to the slots.',
      );
      return;
    }
    setState(() => _busy = true);
    try {
      final r = await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}/api/studio/episodes/$_eid/apply-cuts'),
        headers: _h,
        body: json.encode(_payload()),
      );
      if (!mounted) return;
      if (r.statusCode != 200) {
        _notice('Stitch failed', '(${r.statusCode}) ${r.body}');
        return;
      }
      final j = json.decode(r.body) as Map<String, dynamic>;
      setState(() {
        _title = (j['title'] ?? _title).toString();
        _status = 'Stitched. Master tape preserved.';
      });
      await _post('/api/studio/episodes/$_eid/approve');
      await _post('/api/studio/episodes/$_eid/publish');
      widget.onRefresh();
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        barrierDismissible: false,
        barrierColor: Colors.black.withValues(alpha: 0.8),
        builder: (ctx) => _PublishSuccessDialog(
          title: _title.contains('(Edited Version)')
              ? _title
              : '$_title (Edited Version)',
          onReturn: () {
            Navigator.pop(ctx);
            widget.onBack();
          },
        ),
      );
    } catch (e) {
      _notice('Stitch failed', '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<bool> _post(String path) async {
    try {
      final r = await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}$path'),
        headers: _h,
      );
      return r.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  Future<void> _notice(String title, String body) async {
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      barrierColor: Colors.black.withValues(alpha: 0.8),
      builder: (ctx) => _NoticeDialog(title: title, body: body),
    );
  }

  void _mark(String which) {
    setState(() {
      if (which == 'in') {
        _in = _now;
        if (_out <= _in) _out = _in + 0.1;
      } else {
        _out = _now;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final url = (_active?['url'] ?? '').toString();
    final isAudio = (_active?['kind'] ?? '') == 'audio';
    return ColoredBox(
      color: _void,
      child: Column(
        children: [
          _topBar(),
          Expanded(
            child: LayoutBuilder(
              builder: (context, box) {
                final stacked = box.maxWidth < 980;
                final lib = _libraryPane();
                final trim = _trimmerPane(url, isAudio);
                final board = _storyboardPane();
                if (stacked) {
                  return ListView(
                    children: [
                      SizedBox(height: 260, child: lib),
                      SizedBox(height: 420, child: trim),
                      SizedBox(height: 560, child: board),
                    ],
                  );
                }
                return Row(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Expanded(flex: 22, child: lib),
                    Expanded(flex: 45, child: trim),
                    Expanded(flex: 33, child: board),
                  ],
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _topBar() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
      decoration: const BoxDecoration(
        color: _chamber,
        border: Border(bottom: BorderSide(color: _border)),
      ),
      child: Row(
        children: [
          TextButton.icon(
            onPressed: widget.onBack,
            icon: const Icon(Icons.arrow_back, color: _gold, size: 16),
            label: const Text('Episodes',
                style: TextStyle(color: _gold, fontSize: 12)),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: _elevated,
              border: Border.all(color: _border),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text('Session: $_title',
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(color: _text, fontSize: 11)),
          ),
          const Spacer(),
          Text(_status, style: const TextStyle(color: _muted, fontSize: 11)),
        ],
      ),
    );
  }

  Widget _panel(String label, Widget child, {List<Widget>? actions, Widget? footer}) {
    return Container(
      margin: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: _chamber,
        border: Border.all(color: _border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(10, 8, 8, 6),
            child: Row(
              children: [
                Expanded(
                  child: Text(label,
                      style: const TextStyle(
                          color: _gold, fontSize: 11, letterSpacing: 1)),
                ),
                ...?actions,
              ],
            ),
          ),
          const Divider(height: 1, color: _border),
          Expanded(child: child),
          if (footer != null) footer,
        ],
      ),
    );
  }

  Widget _libraryPane() {
    return _panel(
      'MEDIA LIBRARY',
      ListView(
        padding: const EdgeInsets.all(8),
        children: _library.map((m) {
          final active = identical(m, _active) || (m['id'] == _active?['id']);
          final pinned = m['pinned'] == true;
          final kind = (m['kind'] ?? 'video').toString();
          return InkWell(
            onTap: () => _selectMedia(m),
            child: Container(
              margin: const EdgeInsets.only(bottom: 6),
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: active ? const Color(0xFF1A1A12) : _elevated,
                border: Border.all(
                    color: active ? _gold : _border, width: active ? 1.2 : 1),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    pinned ? 'MASTER' : kind.toUpperCase(),
                    style: TextStyle(
                        color: pinned
                            ? _gold
                            : (kind == 'audio' ? _cyan : _muted),
                        fontSize: 9,
                        letterSpacing: 0.8),
                  ),
                  Text('${m['title']}',
                      style: const TextStyle(color: _text, fontSize: 12)),
                  if (pinned)
                    const Text('Pinned. Never overwritten.',
                        style: TextStyle(color: _muted, fontSize: 10)),
                ],
              ),
            ),
          );
        }).toList(),
      ),
      footer: Padding(
        padding: const EdgeInsets.all(8),
        child: SizedBox(
          width: double.infinity,
          child: OutlinedButton.icon(
            onPressed: _busy ? null : () => _upload(),
            icon: const Icon(Icons.cloud_upload, color: _text, size: 16),
            label: const Text('Upload New Media',
                style: TextStyle(color: _text, fontSize: 12)),
          ),
        ),
      ),
    );
  }

  Widget _trimmerPane(String url, bool isAudio) {
    final cap = _maxFor(_target);
    final over = (_out - _in) > cap + 0.08;
    final audios = _library.where((m) => m['kind'] == 'audio').toList();
    final kind = (_active?['kind'] ?? 'video').toString();
    final badge = kind == 'master'
        ? 'MASTER UNCUT'
        : kind == 'audio'
            ? 'AUDIO'
            : 'VIDEO';
    final maxDur = _duration > 0 ? _duration : 1.0;
    final scrub = _now.clamp(0.0, maxDur);
    return _panel(
      'SOURCE EDITOR',
      ListView(
        padding: const EdgeInsets.all(8),
        children: [
          Text(
            (_active?['title'] ?? 'Select media from library').toString(),
            style: const TextStyle(color: _muted, fontSize: 11),
          ),
          const SizedBox(height: 6),
          SizedBox(
            height: 210,
            child: Stack(
              children: [
                Positioned.fill(
                  child: StudioHtmlMediaPlayer(
                    url: url,
                    isAudio: isAudio,
                    handle: _handle,
                    onDuration: (d) {
                      setState(() {
                        _duration = d;
                        if ((_active?['id'] ?? '') == 'master' ||
                            ((_active?['duration_s'] as num?)?.toDouble() ?? 0) <=
                                0) {
                          _active?['duration_s'] = d;
                        }
                        if (_out > d && d > 0) _out = d;
                      });
                    },
                    onTime: (t) => setState(() => _now = t),
                  ),
                ),
                Positioned(
                  top: 8,
                  left: 8,
                  child: Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: Colors.black54,
                      border: Border.all(color: _border),
                    ),
                    child: Text(badge,
                        style: const TextStyle(
                            color: _gold, fontSize: 9, letterSpacing: 0.8)),
                  ),
                ),
                Positioned(
                  left: 0,
                  right: 0,
                  bottom: 0,
                  child: LinearProgressIndicator(
                    value: _duration > 0 ? (_now / _duration).clamp(0, 1) : 0,
                    minHeight: 4,
                    color: _gold,
                    backgroundColor: const Color(0xFF222222),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              const Text('Scrubber',
                  style: TextStyle(color: _muted, fontSize: 11)),
              const Spacer(),
              Text('${_fmt(_now)} / ${_fmt(_duration)}',
                  style: const TextStyle(color: _muted, fontSize: 11)),
            ],
          ),
          SliderTheme(
            data: SliderTheme.of(context).copyWith(
              activeTrackColor: _gold,
              thumbColor: _gold,
              inactiveTrackColor: _border,
              overlayColor: _gold.withValues(alpha: 0.15),
            ),
            child: Slider(
              value: scrub,
              min: 0,
              max: maxDur,
              onChanged: (v) {
                setState(() => _now = v);
                _handle.seek?.call(v);
              },
            ),
          ),
          Row(
            children: [
              Expanded(child: _markField('IN POINT', _in, 'IN', () => _mark('in'))),
              const SizedBox(width: 8),
              Expanded(
                  child: _markField('OUT POINT', _out, 'OUT', () => _mark('out'))),
            ],
          ),
          if (over)
            Text('Clip ${_fmt(_out - _in)} exceeds slot max ${_fmt(cap)}',
                style: const TextStyle(color: _red, fontSize: 11)),
          const SizedBox(height: 8),
          DropdownButton<int>(
            value: _target,
            dropdownColor: _elevated,
            isExpanded: true,
            items: _slotDefs
                .map((d) => DropdownMenuItem(
                      value: d['id'] as int,
                      child: Text(
                          '${d['id']}. ${d['label']} (Max ${d['maxLabel']})',
                          style: const TextStyle(color: _text, fontSize: 12)),
                    ))
                .toList(),
            onChanged: (v) => setState(() => _target = v ?? 1),
          ),
          if (audios.isNotEmpty)
            DropdownButton<String>(
              value: () {
                final current = (_bgAudio?['id'] ?? '').toString();
                final ids = audios.map((a) => a['id'].toString()).toSet();
                return ids.contains(current) ? current : '';
              }(),
              dropdownColor: _elevated,
              isExpanded: true,
              hint: const Text('Background audio (optional)',
                  style: TextStyle(color: _muted, fontSize: 12)),
              items: [
                const DropdownMenuItem(
                    value: '',
                    child: Text('No background audio',
                        style: TextStyle(color: _muted, fontSize: 12))),
                ...audios.map((a) => DropdownMenuItem(
                      value: a['id'].toString(),
                      child: Text('${a['title']}',
                          style: const TextStyle(color: _cyan, fontSize: 12)),
                    )),
              ],
              onChanged: (v) {
                setState(() {
                  if (v == null || v.isEmpty) {
                    _bgAudio = null;
                  } else {
                    _bgAudio = audios.firstWhere((a) => a['id'] == v);
                  }
                });
              },
            ),
          const SizedBox(height: 8),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: _gold),
            onPressed: _busy ? null : _sendClip,
            child: const Text('+ Add to Storyboard',
                style: TextStyle(color: Colors.black)),
          ),
        ],
      ),
    );
  }

  Widget _markField(String label, double value, String btn, VoidCallback onMark) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label,
            style: const TextStyle(color: _muted, fontSize: 9, letterSpacing: 0.8)),
        const SizedBox(height: 4),
        Container(
          decoration: BoxDecoration(
            color: Colors.black,
            border: Border.all(color: _border),
          ),
          child: Row(
            children: [
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
                  child: Text(_fmt(value),
                      style: const TextStyle(
                          color: _text, fontSize: 12, fontFamily: 'monospace')),
                ),
              ),
              InkWell(
                onTap: onMark,
                child: Container(
                  color: const Color(0xFF1A1A1A),
                  padding:
                      const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                  child: Text(btn,
                      style: const TextStyle(
                          color: _muted, fontSize: 10, fontWeight: FontWeight.bold)),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _storyboardPane() {
    return _panel(
      'PODCAST STRUCTURE',
      ListView(
        padding: const EdgeInsets.fromLTRB(8, 8, 8, 4),
        children: _slots.map(_slotCard).toList(),
      ),
      actions: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          decoration: BoxDecoration(
            color: _elevated,
            border: Border.all(color: _border),
            borderRadius: BorderRadius.circular(4),
          ),
          child: Text('Stitch Time: ${_fmt(_stitchSeconds())}',
              style: const TextStyle(color: _gold, fontSize: 10)),
        ),
      ],
      footer: _storyboardActions(),
    );
  }

  Widget _storyboardActions() {
    return Container(
      padding: const EdgeInsets.fromLTRB(8, 8, 8, 10),
      decoration: const BoxDecoration(
        color: _chamber,
        border: Border(top: BorderSide(color: _border)),
      ),
      child: Row(
        children: [
          Expanded(
            flex: 1,
            child: OutlinedButton.icon(
              onPressed: _busy ? null : _previewStitched,
              icon: const Icon(Icons.movie, color: _text, size: 14),
              label: const Text('Preview',
                  style: TextStyle(color: _text, fontSize: 12)),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            flex: 2,
            child: ElevatedButton.icon(
              style: ElevatedButton.styleFrom(backgroundColor: _gold),
              onPressed: _busy ? null : _approveAndPublish,
              icon: const Icon(Icons.check_circle, color: Colors.black, size: 16),
              label: Text(
                  _busy ? 'Publishing…' : 'Approve & Publish Cut',
                  style: const TextStyle(color: Colors.black, fontSize: 12)),
            ),
          ),
        ],
      ),
    );
  }

  Widget _slotCard(Map<String, dynamic> slot) {
    final clip = slot['clip'];
    final maxS = (slot['max_s'] as num?)?.toDouble() ?? 20;
    final filled = clip is Map;
    var over = false;
    var dur = 0.0;
    if (filled) {
      dur = ((clip['end_s'] as num?)?.toDouble() ?? 0) -
          ((clip['start_s'] as num?)?.toDouble() ?? 0);
      over = dur > maxS + 0.08;
    }
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: filled ? const Color(0xFF0C0C0C) : _void,
        border: Border.all(
          color: filled ? _gold.withValues(alpha: 0.45) : _border,
          style: filled ? BorderStyle.solid : BorderStyle.solid,
        ),
      ),
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (filled) Container(width: 4, color: _gold),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.all(8),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text('${slot['id']}. ${slot['label']}',
                                  style: TextStyle(
                                      color: filled ? _text : _muted,
                                      fontSize: 12)),
                              Text('MAX: ${slot['maxLabel'] ?? _fmt(maxS)}',
                                  style: const TextStyle(
                                      color: _muted, fontSize: 9)),
                            ],
                          ),
                        ),
                        if (filled) ...[
                          TextButton(
                            onPressed: () => _openAdjust(slot),
                            child: const Text('Edit',
                                style: TextStyle(color: _text, fontSize: 10)),
                          ),
                          IconButton(
                            tooltip: 'Remove',
                            onPressed: () => _clearSlot(slot['id'] as int),
                            icon: const Icon(Icons.delete_outline,
                                color: _red, size: 16),
                          ),
                        ],
                      ],
                    ),
                    const SizedBox(height: 6),
                    if (!filled)
                      InkWell(
                        onTap: _busy
                            ? null
                            : () => _upload(intoSlot: slot['id'] as int),
                        child: Container(
                          width: double.infinity,
                          padding: const EdgeInsets.symmetric(vertical: 14),
                          decoration: BoxDecoration(
                            border: Border.all(
                                color: _border, style: BorderStyle.solid),
                          ),
                          child: const Row(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Icon(Icons.cloud_upload, color: _muted, size: 14),
                              SizedBox(width: 6),
                              Text('Upload directly to slot',
                                  style: TextStyle(color: _muted, fontSize: 11)),
                            ],
                          ),
                        ),
                      )
                    else
                      InkWell(
                        onTap: () => _previewSlot(slot),
                        child: Container(
                          width: double.infinity,
                          padding: const EdgeInsets.symmetric(
                              horizontal: 8, vertical: 8),
                          color: Colors.black,
                          child: Row(
                            children: [
                              const Icon(Icons.play_circle_fill,
                                  color: _gold, size: 22),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text('${clip['source_title']}',
                                        overflow: TextOverflow.ellipsis,
                                        style: const TextStyle(
                                            color: _text, fontSize: 11)),
                                    Text(
                                      '${_fmt((clip['start_s'] as num).toDouble())} → ${_fmt((clip['end_s'] as num).toDouble())}  (${_fmt(dur)})',
                                      style: const TextStyle(
                                          color: _gold, fontSize: 10),
                                    ),
                                  ],
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    if (over)
                      const Padding(
                        padding: EdgeInsets.only(top: 4),
                        child: Text('Over slot limit',
                            style: TextStyle(color: _red, fontSize: 11)),
                      ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _NoticeDialog extends StatelessWidget {
  final String title;
  final String body;
  const _NoticeDialog({required this.title, required this.body});

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: _elevated,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 360),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 28, 24, 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.warning_amber_rounded, color: _gold, size: 36),
              const SizedBox(height: 12),
              Text(title,
                  style: const TextStyle(
                      color: _text, fontSize: 16, fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              Text(body,
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: _muted, fontSize: 13)),
              const SizedBox(height: 18),
              ElevatedButton(
                style: ElevatedButton.styleFrom(backgroundColor: _gold),
                onPressed: () => Navigator.pop(context),
                child: const Text('OK', style: TextStyle(color: Colors.black)),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _PublishSuccessDialog extends StatelessWidget {
  final String title;
  final VoidCallback onReturn;
  const _PublishSuccessDialog({required this.title, required this.onReturn});

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: _elevated,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 420),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(height: 4, color: _okGreen),
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 28, 24, 24),
              child: Column(
                children: [
                  Container(
                    width: 64,
                    height: 64,
                    decoration: BoxDecoration(
                      color: _okGreen.withValues(alpha: 0.2),
                      shape: BoxShape.circle,
                    ),
                    child: const Icon(Icons.check, color: _okGreen, size: 36),
                  ),
                  const SizedBox(height: 14),
                  const Text('Publish Successful!',
                      style: TextStyle(
                          color: _text,
                          fontSize: 20,
                          fontWeight: FontWeight.w700)),
                  const SizedBox(height: 8),
                  const Text(
                    'The edit has been stitched and saved to your Vault.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: _muted, fontSize: 13),
                  ),
                  const SizedBox(height: 16),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(12),
                    color: Colors.black,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Title: $title',
                            style: const TextStyle(color: _text, fontSize: 12)),
                        const SizedBox(height: 6),
                        const Text(
                          'Original uncut footage safely retained in Vault.',
                          style: TextStyle(color: _gold, fontSize: 11),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton(
                      style: ElevatedButton.styleFrom(
                          backgroundColor: Colors.white),
                      onPressed: onReturn,
                      child: const Text('Return to Dashboard',
                          style: TextStyle(color: Colors.black)),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _PreviewShell extends StatelessWidget {
  final String title;
  final bool isFinal;
  final Widget child;
  const _PreviewShell(
      {required this.title, required this.isFinal, required this.child});

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: _elevated,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 720),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 8, 8),
              child: Row(
                children: [
                  Icon(isFinal ? Icons.movie : Icons.play_arrow, color: _gold, size: 16),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(title.toUpperCase(),
                        style: const TextStyle(
                            color: _text, fontSize: 12, letterSpacing: 1)),
                  ),
                  IconButton(
                    onPressed: () => Navigator.pop(context),
                    icon: const Icon(Icons.close, color: _muted, size: 18),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
              child: AspectRatio(aspectRatio: 16 / 9, child: child),
            ),
          ],
        ),
      ),
    );
  }
}

class _AdjustPlacedClipDialog extends StatefulWidget {
  final Map<String, dynamic> slot;
  final Map<String, dynamic>? source;
  final double start;
  final double end;
  final double maxS;
  final String maxLabel;
  final String Function(double) fmt;

  const _AdjustPlacedClipDialog({
    required this.slot,
    required this.source,
    required this.start,
    required this.end,
    required this.maxS,
    required this.maxLabel,
    required this.fmt,
  });

  @override
  State<_AdjustPlacedClipDialog> createState() => _AdjustPlacedClipDialogState();
}

class _AdjustPlacedClipDialogState extends State<_AdjustPlacedClipDialog> {
  late final TextEditingController _inCtl;
  late final TextEditingController _outCtl;
  String _warn = '';

  @override
  void initState() {
    super.initState();
    _inCtl = TextEditingController(text: widget.fmt(widget.start));
    _outCtl = TextEditingController(text: widget.fmt(widget.end));
    _warn = 'Max allowed length: ${widget.maxLabel}';
  }

  @override
  void dispose() {
    _inCtl.dispose();
    _outCtl.dispose();
    super.dispose();
  }

  double? _parseClock(String raw) {
    final p = raw.trim().split(':');
    if (p.length == 2) {
      final m = int.tryParse(p[0]);
      final s = double.tryParse(p[1]);
      if (m != null && s != null) return m * 60 + s;
    }
    return double.tryParse(raw.trim());
  }

  void _save() {
    final a = _parseClock(_inCtl.text);
    final b = _parseClock(_outCtl.text);
    if (a == null || b == null) {
      setState(() => _warn = 'Error: Enter times as MM:SS.');
      return;
    }
    if (b <= a) {
      setState(() => _warn = 'Error: Out point must be after In point.');
      return;
    }
    if (b - a > widget.maxS + 0.08) {
      setState(() =>
          _warn = 'Error: Clip exceeds max limit of ${widget.maxLabel}.');
      return;
    }
    Navigator.pop(context, {'in': a, 'out': b});
  }

  @override
  Widget build(BuildContext context) {
    final url = (widget.source?['url'] ?? '').toString();
    final dur = (_parseClock(_outCtl.text) ?? widget.end) -
        (_parseClock(_inCtl.text) ?? widget.start);
    return Dialog(
      backgroundColor: _elevated,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 640),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 8, 8),
              child: Row(
                children: [
                  const Icon(Icons.tune, color: _gold, size: 16),
                  const SizedBox(width: 8),
                  const Expanded(
                    child: Text('ADJUST PLACED CLIP',
                        style: TextStyle(
                            color: _text, fontSize: 12, letterSpacing: 1)),
                  ),
                  IconButton(
                    onPressed: () => Navigator.pop(context),
                    icon: const Icon(Icons.close, color: _muted, size: 18),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Adjusting limits for: ${widget.slot['id']}. ${widget.slot['label']}',
                    style: const TextStyle(color: _muted, fontSize: 12),
                  ),
                  const SizedBox(height: 10),
                  AspectRatio(
                    aspectRatio: 16 / 9,
                    child: Stack(
                      children: [
                        Positioned.fill(
                          child: url.isEmpty
                              ? const ColoredBox(
                                  color: Color(0xFF0A0A0A),
                                  child: Center(
                                    child: Text('Fine Tune Clip',
                                        style: TextStyle(
                                            color: Color(0xFF8B7355),
                                            fontSize: 28,
                                            fontWeight: FontWeight.w300)),
                                  ),
                                )
                              : StudioHtmlMediaPlayer(
                                  url: url,
                                  isAudio:
                                      (widget.source?['kind'] ?? '') == 'audio',
                                  loopStart: widget.start,
                                  loopEnd: widget.end,
                                ),
                        ),
                        Positioned(
                          right: 8,
                          bottom: 8,
                          child: Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 8, vertical: 4),
                            color: Colors.black87,
                            child: Text(widget.fmt(dur < 0 ? 0 : dur),
                                style: const TextStyle(
                                    color: _text, fontSize: 11)),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: _editTime('New In Point', _inCtl),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: _editTime('New Out Point', _outCtl),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(_warn,
                      style: TextStyle(
                          color: _warn.startsWith('Error') ? _red : _gold,
                          fontSize: 11)),
                  const SizedBox(height: 12),
                  const Divider(color: _border, height: 1),
                  const SizedBox(height: 12),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.end,
                    children: [
                      TextButton(
                        onPressed: () => Navigator.pop(context),
                        child: const Text('Cancel',
                            style: TextStyle(color: _text)),
                      ),
                      const SizedBox(width: 8),
                      ElevatedButton(
                        style:
                            ElevatedButton.styleFrom(backgroundColor: _gold),
                        onPressed: _save,
                        child: const Text('Save Adjustment',
                            style: TextStyle(color: Colors.black)),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _editTime(String label, TextEditingController ctl) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(color: _muted, fontSize: 10)),
        const SizedBox(height: 4),
        TextField(
          controller: ctl,
          onChanged: (_) => setState(() {}),
          style: const TextStyle(
              color: _text, fontSize: 13, fontFamily: 'monospace'),
          decoration: const InputDecoration(
            filled: true,
            fillColor: Colors.black,
            isDense: true,
            border: OutlineInputBorder(borderSide: BorderSide(color: _border)),
            enabledBorder:
                OutlineInputBorder(borderSide: BorderSide(color: _border)),
          ),
        ),
      ],
    );
  }
}

class _StitchPreviewDialog extends StatefulWidget {
  final List<Map<String, dynamic>> slots;
  final Map<String, dynamic>? Function(String id) lookup;
  const _StitchPreviewDialog({required this.slots, required this.lookup});

  @override
  State<_StitchPreviewDialog> createState() => _StitchPreviewDialogState();
}

class _StitchPreviewDialogState extends State<_StitchPreviewDialog> {
  int _i = 0;

  Map<String, dynamic> get _slot => widget.slots[_i];
  Map? get _clip => _slot['clip'] as Map?;
  Map<String, dynamic>? get _src =>
      widget.lookup((_clip?['source_id'] ?? 'master').toString());

  @override
  Widget build(BuildContext context) {
    final url = (_src?['url'] ?? '').toString();
    return Dialog(
      backgroundColor: _elevated,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 720),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 8, 8),
              child: Row(
                children: [
                  const Icon(Icons.movie, color: _gold, size: 16),
                  const SizedBox(width: 8),
                  const Expanded(
                    child: Text('FINAL STITCHED VIDEO',
                        style: TextStyle(
                            color: _text, fontSize: 12, letterSpacing: 1)),
                  ),
                  IconButton(
                    onPressed: () => Navigator.pop(context),
                    icon: const Icon(Icons.close, color: _muted, size: 18),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
              child: AspectRatio(
                aspectRatio: 16 / 9,
                child: Stack(
                  children: [
                    Positioned.fill(
                      child: url.isEmpty
                          ? const ColoredBox(
                              color: Color(0xFF0A0A0A),
                              child: Center(
                                child: Text('Stitched Final Video',
                                    style: TextStyle(
                                        color: _gold,
                                        fontSize: 22,
                                        fontWeight: FontWeight.w400)),
                              ),
                            )
                          : StudioHtmlMediaPlayer(
                              key: ValueKey('stitch-$_i-$url'),
                              url: url,
                              isAudio: (_src?['kind'] ?? '') == 'audio',
                              loopStart: (_clip?['start_s'] as num?)?.toDouble(),
                              loopEnd: (_clip?['end_s'] as num?)?.toDouble(),
                            ),
                    ),
                  ],
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
              child: Row(
                children: [
                  Text(
                    '${_slot['label']}  ${_i + 1}/${widget.slots.length}',
                    style: const TextStyle(color: _muted, fontSize: 11),
                  ),
                  const Spacer(),
                  if (_i > 0)
                    TextButton(
                      onPressed: () => setState(() => _i -= 1),
                      child: const Text('Previous'),
                    ),
                  if (_i < widget.slots.length - 1)
                    TextButton(
                      onPressed: () => setState(() => _i += 1),
                      child: const Text('Next'),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
