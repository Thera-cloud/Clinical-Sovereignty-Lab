// Sovereign Studio S1 — Show Setup + Mirror Capture. QUANTUM-CRYSTAL-ARCH
import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher.dart';
import '../config/app_config.dart';
import '../services/coach_web_recorder.dart';
import '../services/studio_livekit_room.dart';

const _lnLabel = 'AI co-host and knowledge companion';
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

class _CoachSovereignStudioTabState extends State<CoachSovereignStudioTab> {
  static const _gold = Color(0xFFC9A962);
  static const _muted = Color(0xFF8B7355);
  static const _text = Color(0xFFE8D5A3);

  final _nameCtrl = TextEditingController();
  final _descCtrl = TextEditingController();
  final _hostCtrl = TextEditingController();
  String _vertical = 'life_coaching';
  bool _ytConnected = false;
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
  String? _sessionId;
  int _complete = 0;
  bool _cloneConsent = false;
  bool _busy = false;
  int? _recordingPart;
  final _recorder = CoachWebRecorder();
  final _noteCtrl = TextEditingController();
  Timer? _tick;
  int _secs = 0;

  Map<String, String> get _h => {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ${widget.token}',
      };

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  @override
  void dispose() {
    _tick?.cancel();
    if (_recordingPart != null) {
      _recorder.stop();
    }
    _nameCtrl.dispose();
    _descCtrl.dispose();
    _hostCtrl.dispose();
    _noteCtrl.dispose();
    super.dispose();
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
        _parts = List<Map<String, dynamic>>.from(j['parts'] ?? []);
        _complete = (j['complete_count'] as num?)?.toInt() ?? 0;
        _cloneConsent = j['clone_consent'] == true;
      }
      if (ytR.statusCode == 200) {
        final j = json.decode(ytR.body) as Map<String, dynamic>;
        _ytConnected = j['connected'] == true;
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
        }
      }
      setState(() {});
    } catch (_) {}
  }

  Future<void> _post(String path, [Map<String, dynamic>? body]) async {
    setState(() => _busy = true);
    final r = await http.post(
      Uri.parse('${AppConfig.apiBaseUrl}$path'),
      headers: _h,
      body: json.encode(body ?? {}),
    );
    if (!mounted) return;
    setState(() => _busy = false);
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(r.statusCode == 200
            ? 'OK'
            : '${r.statusCode}: ${r.body.length > 80 ? r.body.substring(0, 80) : r.body}')));
    if (path == '/api/studio/sessions' && r.statusCode == 200) {
      final j = json.decode(r.body) as Map<String, dynamic>;
      _sessionId = (j['session']?['id'] ?? j['id'] ?? '').toString();
      if ((_sessionId ?? '').isNotEmpty) {
        await _joinRoom();
      }
    }
    await _refresh();
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
      String note = j['jwt'] == true
          ? 'LiveKit JWT ready (guest audio-only).'
          : 'LiveKit pending URL — envelope avatar local.';
      try {
        final eg = await http.post(
          Uri.parse('${AppConfig.apiBaseUrl}/api/studio/sessions/$_sessionId/egress'),
          headers: _h,
          body: json.encode({}),
        );
        if (eg.statusCode == 200) {
          final ej = json.decode(eg.body) as Map<String, dynamic>;
          note += ej['started'] == true
              ? ' Egress started.'
              : ' Egress: ${ej['reason'] ?? 'pending'}.';
        }
      } catch (_) {}
      if (!mounted) return;
      setState(() {
        _roomUrl = roomUrl;
        _lkNote = note;
      });
    }
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
    setState(() => _busy = false);
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(r.statusCode == 200
            ? 'Persona style updated'
            : 'Finalize failed (${r.statusCode})')));
    await _refresh();
  }

  Future<void> _uploadPart(int n, Uint8List bytes, String contentType) async {
    setState(() => _busy = true);
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
    setState(() => _busy = false);
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(r.statusCode == 200
            ? 'Part $n stored (re-record overwrites)'
            : 'Upload failed (${r.statusCode})')));
    await _refresh();
  }

  Future<void> _toggleRecord(int n) async {
    if (!CoachWebRecorder.isSupported) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('In-app record is available on web')));
      return;
    }
    if (_recordingPart == n) {
      _tick?.cancel();
      setState(() {
        _recordingPart = null;
        _busy = true;
      });
      try {
        final bytes = await _recorder.stop();
        if (bytes.isEmpty) {
          if (!mounted) return;
          setState(() => _busy = false);
          ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('No audio captured')));
          return;
        }
        await _uploadPart(n, bytes, _recorder.contentType);
      } catch (e) {
        if (!mounted) return;
        setState(() => _busy = false);
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
    final picked = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: const ['wav', 'mp3', 'm4a', 'ogg', 'webm'],
      withData: true,
      withReadStream: true,
    );
    if (picked == null || picked.files.isEmpty) return;
    final bytes = await _pickedFileBytes(picked.files.first);
    if (bytes == null || bytes.isEmpty) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Could not read audio bytes')));
      return;
    }
    await _uploadPart(n, bytes, 'audio/webm');
  }

  @override
  Widget build(BuildContext context) {
    final clean = (_selected?['clean_published'] as num?)?.toInt() ?? 0;
    final liveReady = clean >= 1;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Little Nate is your $_lnLabel.',
            style: const TextStyle(color: _text, fontSize: 13)),
        const SizedBox(height: 6),
        Text(
          liveReady
              ? 'Live tier unlocked (1 clean published episode).'
              : 'Live tier: $clean/1 clean published episode.',
          style: const TextStyle(color: _muted, fontSize: 12),
        ),
        const SizedBox(height: 16),
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
        if (_lkNote.isNotEmpty)
          Text(_lkNote, style: const TextStyle(color: _muted, fontSize: 11)),
        if (_roomUrl.isNotEmpty) ...[
          TextButton(
            onPressed: () => launchUrl(Uri.parse(_roomUrl),
                mode: LaunchMode.externalApplication,
                webOnlyWindowName: '_blank'),
            child: const Text('Open studio room'),
          ),
          StudioLiveKitRoomEmbed(src: _roomUrl),
        ],
        const SizedBox(height: 16),
        const Text('CALLER MEMORY (counts only)',
            style: TextStyle(color: _gold, fontSize: 11, letterSpacing: 1)),
        Text('logged $_callersLogged · opted-in $_callersOpted · no transcript browse',
            style: const TextStyle(color: _muted, fontSize: 12)),
        const SizedBox(height: 16),
        const Text('EPISODE REVIEW',
            style: TextStyle(color: _gold, fontSize: 11, letterSpacing: 1)),
        const SizedBox(height: 6),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: _gold),
              onPressed: _busy || _selected == null
                  ? null
                  : () => _post('/api/studio/sessions',
                      {'show_id': (_selected?['id'] ?? '').toString()}),
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
        TextField(
          controller: _noteCtrl,
          style: const TextStyle(color: _text, fontSize: 12),
          decoration: const InputDecoration(
            hintText: 'Coach note for regenerate LN answer',
            hintStyle: TextStyle(color: _muted),
          ),
        ),
        if (_episodes.isEmpty)
          const Padding(
            padding: EdgeInsets.only(top: 8),
            child: Text('No episodes yet',
                style: TextStyle(color: _muted, fontSize: 12)),
          ),
        ..._episodes.map((e) {
          final eid = (e['id'] ?? '').toString();
          return ListTile(
            dense: true,
            title: Text('${e['title'] ?? 'Episode'} · ${e['state']}',
                style: const TextStyle(color: _text, fontSize: 12)),
            subtitle: Text('open flags ${e['open_flags'] ?? 0}',
                style: const TextStyle(color: _muted, fontSize: 11)),
            trailing: Wrap(
              spacing: 4,
              children: [
                TextButton(
                  onPressed: _busy ? null : () => _openTranscript(eid),
                  child: const Text('Transcript', style: TextStyle(fontSize: 11)),
                ),
                TextButton(
                  onPressed: _busy
                      ? null
                      : () => _post('/api/studio/episodes/$eid/youtube-upload'),
                  child: const Text('YouTube', style: TextStyle(fontSize: 11)),
                ),
                TextButton(
                  onPressed: _busy
                      ? null
                      : () => _post('/api/studio/episodes/$eid/approve'),
                  child: const Text('Approve', style: TextStyle(fontSize: 11)),
                ),
                TextButton(
                  onPressed: _busy
                      ? null
                      : () => _post('/api/studio/episodes/$eid/publish'),
                  child: const Text('Publish', style: TextStyle(fontSize: 11)),
                ),
                TextButton(
                  onPressed: _busy
                      ? null
                      : () => _post('/api/studio/episodes/$eid/regenerate', {
                            'segment_id': 'ln',
                            'coach_note': _noteCtrl.text.trim(),
                          }),
                  child: const Text('Regen LN', style: TextStyle(fontSize: 11)),
                ),
              ],
            ),
          );
        }),
        const SizedBox(height: 20),
        Text('MIRROR CAPTURE  $_complete/7',
            style: const TextStyle(color: _gold, fontSize: 11, letterSpacing: 1)),
        const SizedBox(height: 8),
        ...(_parts.isEmpty
            ? List.generate(7, (i) => {'index': i + 1, 'title': 'Part ${i + 1}', 'prompt': '', 'complete': false})
            : _parts)
            .map((p) {
          final n = (p['index'] as num?)?.toInt() ?? 0;
          final rec = _recordingPart == n;
          return Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${p['complete'] == true ? '✓' : '○'} ${p['title'] ?? 'Part $n'}',
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
                        onPressed: _busy ? null : () => _toggleRecord(n),
                        icon: Icon(rec ? Icons.stop : Icons.mic,
                            color: Colors.black, size: 16),
                        label: Text(rec ? 'Stop ${_secs}s' : 'Record',
                            style: const TextStyle(color: Colors.black)),
                      ),
                    ElevatedButton.icon(
                      style: ElevatedButton.styleFrom(backgroundColor: _gold),
                      onPressed: _busy ? null : () => _pickPart(n),
                      icon: const Icon(Icons.upload_file,
                          color: Colors.black, size: 16),
                      label: const Text('Upload',
                          style: TextStyle(color: Colors.black)),
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
          onPressed: _busy ? null : _finalize,
          child: const Text('Finalize capture → persona style',
              style: TextStyle(color: Colors.black)),
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
