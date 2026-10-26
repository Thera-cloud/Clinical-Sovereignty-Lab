import 'dart:convert';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:speech_to_text/speech_to_text.dart';

/// Host teleprompter overlay. Paste or load a script, tap a word, optional follow.
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
      duration: const Duration(milliseconds: 280),
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

  void _onHeard(String raw) {
    if (!_follow || _words.isEmpty) return;
    final heard = raw
        .split(RegExp(r'\s+'))
        .map(_norm)
        .where((w) => w.length > 1)
        .toList();
    if (heard.isEmpty) return;
    final take = heard.length >= 4 ? heard.sublist(heard.length - 4) : heard;
    final start = _cursor;
    final end = (_cursor + 12).clamp(0, _words.length);
    var best = -1;
    var bestHit = 0;
    for (var i = start; i < end; i++) {
      var hit = 0;
      for (var k = 0; k < take.length && i + k < _words.length; k++) {
        if (_norm(_words[i + k]) == take[k]) hit++;
      }
      if (hit > bestHit) {
        bestHit = hit;
        best = i + take.length - 1;
      }
    }
    if (bestHit >= (take.length >= 3 ? 2 : 1) && best > _cursor) {
      _jump(best);
    }
  }

  Future<void> _toggleFollow() async {
    if (_follow) {
      await _speech.stop();
      setState(() {
        _follow = false;
        _listening = false;
      });
      return;
    }
    final ok = await _speech.initialize();
    if (!ok || !mounted) return;
    setState(() => _follow = true);
    await _speech.listen(
      onResult: (r) => _onHeard(r.recognizedWords),
      listenMode: ListenMode.dictation,
      partialResults: true,
      pauseFor: const Duration(seconds: 8),
      listenFor: const Duration(minutes: 30),
    );
    if (mounted) setState(() => _listening = true);
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
      onTap: () => setState(() => _open = true),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: _bg,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: _gold),
        ),
        child: const Text('Teleprompter',
            style: TextStyle(color: _gold, fontSize: 12, fontWeight: FontWeight.w600)),
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
          _top = (_top + d.delta.dy).clamp(0, MediaQuery.sizeOf(context).height - 80);
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
                        color: _gold, fontSize: 13, fontWeight: FontWeight.w600)),
                const Spacer(),
                TextButton(
                  onPressed: _toggleFollow,
                  child: Text(_follow ? 'Following' : 'Follow me',
                      style: TextStyle(
                          color: _follow ? _gold : _dim, fontSize: 12)),
                ),
                IconButton(
                  icon: const Icon(Icons.close, color: _dim, size: 18),
                  onPressed: () async {
                    await _speech.stop();
                    setState(() {
                      _open = false;
                      _follow = false;
                      _listening = false;
                    });
                  },
                ),
              ]),
            ),
            if (_words.isEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
                child: Column(children: [
                  TextField(
                    controller: _paste,
                    maxLines: 5,
                    style: const TextStyle(color: _ink, fontSize: 14, height: 1.4),
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
                      onPressed: () {
                        _speech.stop();
                        setState(() {
                          _words = [];
                          _cursor = 0;
                          _follow = false;
                          _listening = false;
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
