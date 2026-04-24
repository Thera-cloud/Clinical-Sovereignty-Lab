import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';

abstract class PickedLargeVideo {
  String get name;
  int get size;
  String get contentType;
  Future<Uint8List> readChunk(int start, int end);
  void dispose();
}

class _IoPickedVideo implements PickedLargeVideo {
  _IoPickedVideo({
    required this.name,
    required this.size,
    required this.contentType,
    required this._raf,
  });

  @override
  final String name;
  @override
  final int size;
  @override
  final String contentType;

  final RandomAccessFile _raf;

  @override
  Future<Uint8List> readChunk(int start, int end) async {
    final length = end - start;
    if (length <= 0) return Uint8List(0);
    await _raf.setPosition(start);
    return await _raf.read(length);
  }

  @override
  void dispose() {
    try {
      _raf.closeSync();
    } catch (_) {}
  }
}

String _guessContentType(String name) {
  final ext = name.toLowerCase().split('.').last;
  switch (ext) {
    case 'mp4':
      return 'video/mp4';
    case 'mov':
      return 'video/quicktime';
    case 'webm':
      return 'video/webm';
    case 'mkv':
      return 'video/x-matroska';
    case 'avi':
      return 'video/x-msvideo';
    default:
      return 'application/octet-stream';
  }
}

Future<PickedLargeVideo?> pickLargeVideo() async {
  final result = await FilePicker.platform.pickFiles(
    type: FileType.video,
    allowMultiple: false,
    withData: false,
    withReadStream: false,
  );
  if (result == null || result.files.isEmpty) return null;
  final pf = result.files.first;
  final path = pf.path;
  if (path == null || path.isEmpty) {
    throw StateError('Picked file has no native path');
  }
  final file = File(path);
  if (!file.existsSync()) {
    throw StateError('Picked file no longer exists at $path');
  }
  final raf = await file.open(mode: FileMode.read);
  return _IoPickedVideo(
    name: pf.name,
    size: pf.size,
    contentType: _guessContentType(pf.name),
    _raf: raf,
  );
}
