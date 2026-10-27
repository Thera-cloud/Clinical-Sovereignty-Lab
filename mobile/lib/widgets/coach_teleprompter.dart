import 'dart:convert';
import 'dart:math' as math;

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:speech_to_text/speech_to_text.dart';

/// Host teleprompter overlay. Paste or load a script; gold word follows speech.
class CoachTeleprompterOverlay extends StatefulWidget {
  const CoachTeleprompterOverlay({super.key});

  @override
  State<CoachTeleprompterOverlay> createState() =>
      _CoachTeleprompterOverlayState();
}

class _CoachTeleprompterOverlayState extends State<CoachTeleprompterOverlay> {
  static const _gold = Color(0xFFC9A962);
  static const _dim = Color(0xFF8B7355);
  static const _ink = Color(0xFFE8D5A3);
  static const _bg = Color(0xE6111111);

  final _paste = TextEditingController();
  final _speech = SpeechToText();
  final _wordKeys = <GlobalKey>[];
  bool _open = false;
  bool _follow = false;
  bool _listening = false;
  bool _inited = false;
  bool _restarting = false;
  String? _micHint;
  double _left = 16;
  double _top = 88;
  List<String> _words = [];
  int _cursor = 0;

  @override
  void dispose() {
    _follow = false;
    _speech.stop();
    _paste.dispose();
    super.dispose();
  }

  Future<bool> _ensureInit() async {
    if (_inited) return true;
    try {
      final ok = await _speech.initialize(
        onError: (e) {
          if (!_follow) return;
          if (mounted) {
            setState(() {
              _listening = false;
              _micHint = e.errorMsg.isNotEmpty
                  ? 'Mic: ${e.errorMsg}'
                  : 'Allow the microphone for this site.';
            });
          }
          _scheduleRestart();
        },
        onStatus: (status) {
          if (!_follow) return;
          if (status == 'listening') {
            if (mounted) setState(() => _listening = true);
            return;
          }
          if (status == 'done' || status == 'notListening') {
            if (mounted) setState(() => _listening = false);
            _scheduleRestart();
          }
        },
      );
      _inited = ok;
      return ok;
    } catch (_) {
      _inited = false;
      return false;
    }
  }

  void _scheduleRestart() {
    if (!_follow || _restarting || _words.isEmpty) return;
    _restarting = true;
    Future.delayed(const Duration(milliseconds: 160), () async {
      _restarting = false;
      if (!_follow || !mounted || _words.isEmpty) return;
      if (_speech.isListening) return;
      await _listenLoop();
    });
  }

  Future<void> _listenLoop() async {
    if (!_follow || _words.isEmpty) return;
    if (_speech.isListening) return;
    try {
      await _speech.listen(
        onResult: (r) {
          final text = r.recognizedWords.trim();
          if (text.isNotEmpty) _onHeard(text);
        },
        localeId: 'en-US',
        listenOptions: SpeechListenOptions(
          partialResults: true,
          listenMode: ListenMode.dictation,
          cancelOnError: false,
        ),
      );
      if (mounted) setState(() => _listening = true);
    } catch (_) {
      if (mounted) setState(() => _listening = false);
      _scheduleRestart();
    }
  }

  Future<void> _startFollow() async {
    if (_words.isEmpty) return;
    setState(() {
      _follow = true;
      _micHint = null;
    });
    final ok = await _ensureInit();
    if (!ok || !mounted) {
      setState(() {
        _follow = false;
        _listening = false;
        _micHint = 'Allow the microphone, then tap Follow me.';
      });
      return;
    }
    await _listenLoop();
  }

  Future<void> _stopFollow() async {
    _follow = false;
    try {
      await _speech.stop();
    } catch (_) {}
    if (mounted) {
      setState(() => _listening = false);
    }
  }

  void _setScript(String raw) {
    final words =
        raw.split(RegExp(r'\s+')).where((w) => w.isNotEmpty).toList();
    _wordKeys
      ..clear()
      ..addAll(List.generate(words.length, (_) => GlobalKey()));
    setState(() {
      _words = words;
      _cursor = 0;
      _paste.text = raw;
    });
    WidgetsBinding.instance.addPostFrameCallback((_) => _reveal(_cursor));
    _startFollow();
  }

  Future<void> _pickFile() async {
    final r = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: const ['txt', 'md'],
      withData: true,
    );
    if (r == null || r.files.isEmpty) return;
    final bytes = r.files.first.bytes;
    if (bytes == null || bytes.isEmpty) return;
    _setScript(utf8.decode(bytes, allowMalformed: true));
  }

  void _reveal(int i) {
    if (i < 0 || i >= _wordKeys.length) return;
    final ctx = _wordKeys[i].currentContext;
    if (ctx == null) return;
    Scrollable.ensureVisible(
      ctx,
      alignment: 0.35,
      duration: const Duration(milliseconds: 220),
      curve: Curves.easeOut,
    );
  }

  void _jump(int i) {
    if (_words.isEmpty) return;
    final n = i.clamp(0, _words.length - 1);
    setState(() => _cursor = n);
    WidgetsBinding.instance.addPostFrameCallback((_) => _reveal(n));
  }

  String _norm(String w) =>
      w.toLowerCase().replaceAll(RegExp(r"[^a-z0-9']"), '');

  bool _fuzzy(String a, String b) {
    if (a == b) return true;
    if (a.isEmpty || b.isEmpty) return false;
    if ((a.length - b.length).abs() > 1) return false;
    if (a.length < 4 || b.length < 4) return false;
    if (a.length == b.length) {
      var d = 0;
      for (var i = 0; i < a.length; i++) {
        if (a.codeUnitAt(i) != b.codeUnitAt(i)) d++;
        if (d > 1) return false;
      }
      return true;
    }
    final longer = a.length > b.length ? a : b;
    final shorter = a.length > b.length ? b : a;
    var i = 0;
    var j = 0;
    var skipped = false;
    while (i < longer.length && j < shorter.length) {
      if (longer.codeUnitAt(i) == shorter.codeUnitAt(j)) {
        i++;
        j++;
      } else {
        if (skipped) return false;
        skipped = true;
        i++;
      }
    }
    return true;
  }

  int? _locate(List<String> heard) {
    if (heard.isEmpty || _words.isEmpty) return null;
    final from = math.max(0, _cursor - 2);
    final to = math.min(_words.length, _cursor + 22);
    for (var n = math.min(5, heard.length); n >= 1; n--) {
      final needle = heard.sublist(heard.length - n);
      int? hit;
      for (var i = from; i + n <= to; i++) {
        if (n == 1 && i < _cursor) continue;
        var ok = true;
        for (var k = 0; k < n; k++) {
          if (!_fuzzy(_norm(_words[i + k]), needle[k])) {
            ok = false;
            break;
          }
        }
        if (ok) {
          hit = i + n - 1;
          if (n == 1) break;
        }
      }
      if (hit != null) return hit;
    }
    return null;
  }

  void _onHeard(String raw) {
    if (!_follow || _words.isEmpty) return;
    final heard = raw
        .split(RegExp(r'\s+'))
        .map(_norm)
        .where((w) => w.isNotEmpty)
        .toList();
    if (heard.isEmpty) return;
    final found = _locate(heard);
    if (found != null && found != _cursor) _jump(found);
  }

  @override
  Widget build(BuildContext context) {
    return Positioned(
      left: _left,
      top: _top,
      child: Material(
        color: Colors.transparent,
        child: _open ? _panel(context) : _pill(),
      ),
    );
  }

  Widget _pill() {
    return GestureDetector(
      onTap: () {
        setState(() => _open = true);
        if (_words.isNotEmpty) _startFollow();
      },
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: _bg,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: _gold),
        ),
        child: const Text('Teleprompter',
            style: TextStyle(
                color: _gold, fontSize: 12, fontWeight: FontWeight.w600)),
      ),
    );
  }

  Widget _panel(BuildContext context) {
    final maxW = MediaQuery.sizeOf(context).width;
    final width = maxW < 520 ? maxW - 24 : 440.0;
    return GestureDetector(
      onPanUpdate: (d) {
        setState(() {
          _left = (_left + d.delta.dx).clamp(0, maxW - 80);
          _top =
              (_top + d.delta.dy).clamp(0, MediaQuery.sizeOf(context).height - 80);
        });
      },
      child: Container(
        width: width,
        constraints: const BoxConstraints(maxHeight: 340),
        decoration: BoxDecoration(
          color: _bg,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: _gold.withValues(alpha: 0.7)),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 8, 8, 4),
              child: Row(children: [
                const Text('Teleprompter',
                    style: TextStyle(
                        color: _gold,
                        fontSize: 13,
                        fontWeight: FontWeight.w600)),
                const Spacer(),
                TextButton(
                  onPressed: () {
                    if (_follow) {
                      _stopFollow();
                    } else {
                      _startFollow();
                    }
                  },
                  child: Text(
                    _follow ? 'Listening' : 'Follow me',
                    style: TextStyle(
                        color: _follow ? _gold : _dim, fontSize: 12),
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.close, color: _dim, size: 18),
                  onPressed: () async {
                    await _stopFollow();
                    if (mounted) setState(() => _open = false);
                  },
                ),
              ]),
            ),
            if (_micHint != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 0, 12, 6),
                child: Text(_micHint!,
                    style: const TextStyle(color: _dim, fontSize: 11)),
              ),
            if (_words.isEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
                child: Column(children: [
                  TextField(
                    controller: _paste,
                    maxLines: 5,
                    style: const TextStyle(
                        color: _ink, fontSize: 14, height: 1.4),
                    decoration: const InputDecoration(
                      hintText: 'Paste what you want to say',
                      hintStyle: TextStyle(color: _dim, fontSize: 13),
                      border: InputBorder.none,
                    ),
                  ),
                  Row(children: [
                    TextButton(
                        onPressed: () {
                          if (_paste.text.trim().isNotEmpty) {
                            _setScript(_paste.text);
                          }
                        },
                        child: const Text('Use this',
                            style: TextStyle(color: _gold, fontSize: 12))),
                    TextButton(
                        onPressed: _pickFile,
                        child: const Text('Load file',
                            style: TextStyle(color: _dim, fontSize: 12))),
                  ]),
                ]),
              )
            else
              Flexible(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.fromLTRB(14, 0, 14, 8),
                  child: Wrap(
                    spacing: 4,
                    runSpacing: 6,
                    children: [
                      for (var i = 0; i < _words.length; i++)
                        GestureDetector(
                          onTap: () => _jump(i),
                          child: Text(
                            _words[i],
                            key: _wordKeys[i],
                            style: TextStyle(
                              fontSize: 18,
                              height: 1.55,
                              color: i == _cursor
                                  ? _gold
                                  : (i < _cursor ? _dim : _ink),
                              fontWeight: i == _cursor
                                  ? FontWeight.w600
                                  : FontWeight.w400,
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              ),
            if (_words.isNotEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(8, 0, 8, 8),
                child: Row(children: [
                  TextButton(
                      onPressed: () => _jump(_cursor - 1),
                      child: const Text('Back',
                          style: TextStyle(color: _dim, fontSize: 12))),
                  TextButton(
                      onPressed: () => _jump(_cursor + 1),
                      child: const Text('Next',
                          style: TextStyle(color: _gold, fontSize: 12))),
                  const Spacer(),
                  if (_listening)
                    const Text('Listening',
                        style: TextStyle(color: _gold, fontSize: 11)),
                  TextButton(
                      onPressed: () async {
                        await _stopFollow();
                        setState(() {
                          _words = [];
                          _cursor = 0;
                        });
                      },
                      child: const Text('Clear',
                          style: TextStyle(color: _dim, fontSize: 12))),
                ]),
              ),
          ],
        ),
      ),
    );
  }
}
