// ignore: avoid_web_libraries_in_flutter
import 'dart:async';
import 'dart:html' as html;
import 'dart:typed_data';

abstract class PickedLargeVideo {
  String get name;
  int get size;
  String get contentType;

  /// Reads bytes in the half-open range [start, end). Implementation
  /// must be true-streaming — it MUST NOT load the entire file into
  /// memory at any point. On web we use Blob.slice() + FileReader.
  Future<Uint8List> readChunk(int start, int end);

  void dispose();
}

class _WebPickedVideo implements PickedLargeVideo {
  _WebPickedVideo(this._file);

  final html.File _file;

  @override
  String get name => _file.name;

  @override
  int get size => _file.size;

  @override
  String get contentType => _file.type.isEmpty ? 'video/mp4' : _file.type;

  @override
  Future<Uint8List> readChunk(int start, int end) async {
    final blob = _file.slice(start, end);
    final reader = html.FileReader();
    final completer = Completer<Uint8List>();
    reader.onLoadEnd.listen((_) {
      final res = reader.result;
      if (res is List<int>) {
        completer.complete(Uint8List.fromList(res));
      } else if (res is ByteBuffer) {
        completer.complete(res.asUint8List());
      } else {
        completer.completeError(
          StateError('Unexpected FileReader result: ${res.runtimeType}'),
        );
      }
    });
    reader.onError.listen((e) => completer.completeError(e));
    reader.readAsArrayBuffer(blob);
    return completer.future;
  }

  @override
  void dispose() {
    // No persistent handle to release; the html.File goes out of scope
    // with this object and the browser frees the underlying resource.
  }
}

/// Opens a hidden `<input type="file" accept="video/*">`, awaits the
/// user's selection, and returns a streaming-capable handle backed by
/// the original `html.File` (NOT a Uint8List). This is what makes 3 GB
/// uploads possible on the web — we never hand the entire file to the
/// JS heap.
Future<PickedLargeVideo?> pickLargeVideo() async {
  final input = html.FileUploadInputElement()..accept = 'video/*';
  // Some browsers ignore .click() on an input that's not in the DOM.
  input.style.display = 'none';
  html.document.body?.append(input);

  final completer = Completer<PickedLargeVideo?>();

  void cleanup() {
    try {
      input.remove();
    } catch (_) {}
  }

  input.onChange.listen((_) {
    final files = input.files;
    if (files == null || files.isEmpty) {
      cleanup();
      completer.complete(null);
      return;
    }
    cleanup();
    completer.complete(_WebPickedVideo(files.first));
  });

  // The browser does not fire `change` if the user dismisses the dialog.
  // We rely on the user hitting the button again rather than racing a
  // synthetic timeout (which would risk completing twice).
  input.click();
  return completer.future;
}
