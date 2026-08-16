import 'dart:async';
import 'dart:html' as html;
import 'dart:typed_data';

/// Browser mic → webm via MediaRecorder (no third-party license).
class CoachWebRecorder {
  static bool get isSupported => true;

  html.MediaRecorder? _rec;
  html.MediaStream? _stream;
  final List<html.Blob> _chunks = [];
  Completer<void>? _stopped;
  bool _recording = false;

  bool get isRecording => _recording;
  String get contentType => 'audio/webm';

  Future<void> start() async {
    final devices = html.window.navigator.mediaDevices;
    if (devices == null) {
      throw StateError('Microphone not available');
    }
    await stop();
    _chunks.clear();
    _stream = await devices.getUserMedia({'audio': true, 'video': false});
    var mime = 'audio/webm';
    if (html.MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
      mime = 'audio/webm;codecs=opus';
    }
    _rec = html.MediaRecorder(_stream!, {'mimeType': mime});
    _stopped = Completer<void>();
    _rec!.addEventListener('dataavailable', (event) {
      if (event is html.BlobEvent && event.data != null && event.data!.size > 0) {
        _chunks.add(event.data!);
      }
    });
    _rec!.addEventListener('stop', (_) {
      final c = _stopped;
      if (c != null && !c.isCompleted) {
        c.complete();
      }
    });
    _rec!.start();
    _recording = true;
  }

  Future<Uint8List> stop() async {
    if (_rec == null && _stream == null) {
      _recording = false;
      return Uint8List(0);
    }
    _recording = false;
    try {
      _rec?.stop();
    } catch (_) {}
    try {
      await _stopped?.future.timeout(const Duration(seconds: 4));
    } catch (_) {}
    _stream?.getTracks().forEach((t) => t.stop());
    _stream = null;
    _rec = null;
    _stopped = null;
    if (_chunks.isEmpty) {
      return Uint8List(0);
    }
    final blob = html.Blob(_chunks, 'audio/webm');
    _chunks.clear();
    final reader = html.FileReader();
    final done = Completer<Uint8List>();
    reader.onLoad.listen((_) {
      final raw = reader.result;
      if (raw is ByteBuffer) {
        done.complete(Uint8List.view(raw));
      } else {
        done.complete(Uint8List(0));
      }
    });
    reader.onError.listen((_) {
      if (!done.isCompleted) {
        done.complete(Uint8List(0));
      }
    });
    reader.readAsArrayBuffer(blob);
    return done.future.timeout(
      const Duration(seconds: 8),
      onTimeout: () => Uint8List(0),
    );
  }
}
