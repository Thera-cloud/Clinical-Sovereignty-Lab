import 'dart:async';
import 'dart:html' as html;
import 'dart:typed_data';

/// Browser mic → webm/mp4 via MediaRecorder (no third-party license).
class CoachWebRecorder {
  static bool get isSupported => true;

  static const _mimeCandidates = <String>[
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/mp4',
    'audio/mp4;codecs=mp4a.40.2',
    'audio/aac',
  ];

  html.MediaRecorder? _rec;
  html.MediaStream? _stream;
  final List<html.Blob> _chunks = [];
  Completer<void>? _stopped;
  bool _recording = false;
  String _mime = 'audio/webm';

  bool get isRecording => _recording;

  String get contentType {
    if (_mime.startsWith('audio/mp4') || _mime.startsWith('audio/aac')) {
      return 'audio/mp4';
    }
    return 'audio/webm';
  }

  html.MediaRecorder _makeRecorder(html.MediaStream stream) {
    for (final mime in _mimeCandidates) {
      if (!html.MediaRecorder.isTypeSupported(mime)) {
        continue;
      }
      try {
        final rec = html.MediaRecorder(stream, {'mimeType': mime});
        _mime = mime;
        return rec;
      } catch (_) {}
    }
    _mime = 'audio/webm';
    return html.MediaRecorder(stream);
  }

  Future<void> start() async {
    final devices = html.window.navigator.mediaDevices;
    if (devices == null) {
      throw StateError('Microphone not available');
    }
    await stop();
    _chunks.clear();
    _stream = await devices.getUserMedia({'audio': true, 'video': false});
    _rec = _makeRecorder(_stream!);
    _stopped = Completer<void>();
    _rec!.addEventListener('dataavailable', (event) {
      html.Blob? data;
      if (event is html.BlobEvent) {
        data = event.data;
      } else {
        try {
          final raw = (event as dynamic).data;
          if (raw is html.Blob) {
            data = raw;
          }
        } catch (_) {}
      }
      if (data != null && data.size > 0) {
        _chunks.add(data);
      }
    });
    _rec!.addEventListener('stop', (_) {
      final c = _stopped;
      if (c != null && !c.isCompleted) {
        c.complete();
      }
    });
    // Timeslice so Safari/Chrome emit chunks before stop.
    _rec!.start(250);
    _recording = true;
  }

  static Uint8List bytesFromReaderResult(Object? raw) {
    if (raw is Uint8List) {
      return raw;
    }
    if (raw is ByteBuffer) {
      return Uint8List.view(raw);
    }
    if (raw is TypedData) {
      return Uint8List.view(
        raw.buffer,
        raw.offsetInBytes,
        raw.lengthInBytes,
      );
    }
    return Uint8List(0);
  }

  Future<Uint8List> stop() async {
    if (_rec == null && _stream == null) {
      _recording = false;
      return Uint8List(0);
    }
    _recording = false;
    try {
      _rec?.requestData();
    } catch (_) {}
    try {
      _rec?.stop();
    } catch (_) {}
    try {
      await _stopped?.future.timeout(const Duration(seconds: 4));
    } catch (_) {}
    await Future<void>.delayed(const Duration(milliseconds: 80));
    _stream?.getTracks().forEach((t) => t.stop());
    _stream = null;
    _rec = null;
    _stopped = null;
    if (_chunks.isEmpty) {
      return Uint8List(0);
    }
    final blob = html.Blob(_chunks, contentType);
    _chunks.clear();
    final reader = html.FileReader();
    final done = Completer<Uint8List>();
    reader.onLoad.listen((_) {
      if (!done.isCompleted) {
        done.complete(bytesFromReaderResult(reader.result));
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
