import 'dart:io';
import 'dart:typed_data';

import 'package:path_provider/path_provider.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:record/record.dart';

/// Native mic via `record`. Audio only — not a voice clone.
class CoachWebRecorder {
  static bool get isSupported => true;

  final AudioRecorder _rec = AudioRecorder();
  String? _path;
  bool _recording = false;

  bool get isRecording => _recording;
  String get contentType => 'audio/mp4';

  Future<void> start() async {
    final granted = await Permission.microphone.request();
    if (!granted.isGranted) {
      throw StateError('Microphone permission denied');
    }
    if (!await _rec.hasPermission()) {
      throw StateError('Recorder permission denied');
    }
    await stop();
    final dir = await getTemporaryDirectory();
    _path = '${dir.path}/coach_interview.m4a';
    await _rec.start(
      const RecordConfig(encoder: AudioEncoder.aacLc, numChannels: 1),
      path: _path!,
    );
    _recording = true;
  }

  Future<Uint8List> stop() async {
    _recording = false;
    String? path;
    try {
      path = await _rec.stop();
    } catch (_) {}
    path ??= _path;
    _path = null;
    if (path == null || path.isEmpty) {
      return Uint8List(0);
    }
    final file = File(path);
    if (!await file.exists()) {
      return Uint8List(0);
    }
    return file.readAsBytes();
  }
}
