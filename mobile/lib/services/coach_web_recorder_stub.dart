import 'dart:typed_data';

class CoachWebRecorder {
  static bool get isSupported => false;
  bool get isRecording => false;
  String get contentType => 'audio/webm';

  Future<void> start() async {
    throw UnsupportedError('In-app record unavailable on this platform');
  }

  Future<Uint8List> stop() async {
    throw UnsupportedError('In-app record unavailable on this platform');
  }
}
