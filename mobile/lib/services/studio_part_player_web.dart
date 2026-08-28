import 'dart:html' as html;
import 'dart:typed_data';

html.AudioElement? _el;
String? _url;

void playStudioBytes(Uint8List bytes, String mime) {
  stopStudioPlayback();
  final blob = html.Blob([bytes], mime.isEmpty ? 'audio/webm' : mime);
  _url = html.Url.createObjectUrlFromBlob(blob);
  _el = html.AudioElement()
    ..src = _url!
    ..autoplay = true;
  _el!.play();
}

void stopStudioPlayback() {
  _el?.pause();
  _el = null;
  if (_url != null) {
    html.Url.revokeObjectUrl(_url!);
    _url = null;
  }
}
