/// Fallback for unsupported platforms. Throws if invoked.
import 'dart:typed_data';

abstract class PickedLargeVideo {
  String get name;
  int get size;
  String get contentType;
  Future<Uint8List> readChunk(int start, int end);
  void dispose();
}

Future<PickedLargeVideo?> pickLargeVideo() async {
  throw UnsupportedError('Large-video picker not available on this platform.');
}
