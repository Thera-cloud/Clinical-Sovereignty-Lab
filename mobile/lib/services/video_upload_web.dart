// ignore: avoid_web_libraries_in_flutter
import 'dart:async';
import 'dart:convert';
import 'dart:html' as html;
import 'dart:typed_data';

const int _chunkSize = 50 * 1024 * 1024; // 50MB per chunk (within Cloudflare 100MB limit)

/// Uploads a video file using chunked upload to bypass Cloudflare's 100MB limit.
///
/// Splits the file into 50MB chunks, uploads each via the browser's native
/// FormData + XMLHttpRequest, then calls finalize to reassemble on the server.
Future<Map<String, dynamic>> uploadVideoNative({
  required String url,
  required String token,
  required String coachId,
  required String clientId,
  required Uint8List bytes,
  required String filename,
  void Function(double progress)? onProgress,
}) async {
  final totalSize = bytes.length;
  final totalChunks = (totalSize / _chunkSize).ceil();
  final uploadId = 'UP_${DateTime.now().millisecondsSinceEpoch}_$totalSize';
  final baseUrl = url.replaceAll('/upload-video', '');

  html.window.console.log('[Upload] Starting chunked upload: $totalChunks chunks, '
      '${(totalSize / 1024 / 1024).toStringAsFixed(1)} MB total');

  for (int i = 0; i < totalChunks; i++) {
    final start = i * _chunkSize;
    final end = (start + _chunkSize > totalSize) ? totalSize : start + _chunkSize;
    final chunkBytes = bytes.sublist(start, end);

    html.window.console.log('[Upload] Sending chunk ${i + 1}/$totalChunks '
        '(${(chunkBytes.length / 1024 / 1024).toStringAsFixed(1)} MB)');

    await _sendChunk(
      url: '$baseUrl/upload-chunk',
      token: token,
      uploadId: uploadId,
      chunkIndex: i,
      totalChunks: totalChunks,
      chunkBytes: chunkBytes,
      filename: filename,
      coachId: coachId,
      clientId: clientId,
      onProgress: (chunkProgress) {
        if (onProgress != null) {
          final overallProgress = (i + chunkProgress) / totalChunks;
          onProgress(overallProgress);
        }
      },
    );

    html.window.console.log('[Upload] Chunk ${i + 1}/$totalChunks complete');
  }

  html.window.console.log('[Upload] All chunks sent, finalizing...');
  onProgress?.call(0.95);

  final result = await _finalize(
    url: '$baseUrl/upload-finalize',
    token: token,
    uploadId: uploadId,
  );

  html.window.console.log('[Upload] Finalize complete: ${result['video_id']}');
  onProgress?.call(1.0);
  return result;
}

Future<Map<String, dynamic>> _sendChunk({
  required String url,
  required String token,
  required String uploadId,
  required int chunkIndex,
  required int totalChunks,
  required Uint8List chunkBytes,
  required String filename,
  required String coachId,
  required String clientId,
  void Function(double)? onProgress,
}) async {
  final completer = Completer<Map<String, dynamic>>();

  final blob = html.Blob([chunkBytes], 'application/octet-stream');
  final formData = html.FormData();
  formData.appendBlob('file', blob, 'chunk_$chunkIndex');
  formData.append('upload_id', uploadId);
  formData.append('chunk_index', chunkIndex.toString());
  formData.append('total_chunks', totalChunks.toString());
  formData.append('filename', filename);
  formData.append('coach_id', coachId);
  formData.append('client_id', clientId);

  final xhr = html.HttpRequest();
  xhr.open('POST', url);
  xhr.setRequestHeader('Authorization', 'Bearer $token');

  xhr.upload.onProgress.listen((event) {
    if (event.lengthComputable && onProgress != null) {
      onProgress(event.loaded! / event.total!);
    }
  });

  xhr.onLoad.listen((_) {
    final status = xhr.status ?? 0;
    final body = xhr.responseText ?? '';
    if (status == 200) {
      try {
        final decoded = jsonDecode(body);
        completer.complete(decoded is Map ? Map<String, dynamic>.from(decoded) : <String, dynamic>{});
      } catch (e) {
        completer.completeError('Chunk $chunkIndex: parse error: $e');
      }
    } else {
      completer.completeError('Chunk $chunkIndex: server returned $status: $body');
    }
  });

  xhr.onError.listen((_) {
    completer.completeError('Chunk $chunkIndex: network error');
  });

  xhr.onAbort.listen((_) {
    completer.completeError('Chunk $chunkIndex: aborted');
  });

  xhr.send(formData);
  return completer.future;
}

Future<Map<String, dynamic>> _finalize({
  required String url,
  required String token,
  required String uploadId,
}) async {
  final completer = Completer<Map<String, dynamic>>();

  final formData = html.FormData();
  formData.append('upload_id', uploadId);

  final xhr = html.HttpRequest();
  xhr.open('POST', url);
  xhr.setRequestHeader('Authorization', 'Bearer $token');

  xhr.onLoad.listen((_) {
    final status = xhr.status ?? 0;
    final body = xhr.responseText ?? '';
    if (status == 200) {
      try {
        final decoded = jsonDecode(body);
        completer.complete(decoded is Map ? Map<String, dynamic>.from(decoded) : <String, dynamic>{});
      } catch (e) {
        completer.completeError('Finalize parse error: $e');
      }
    } else {
      completer.completeError('Finalize: server returned $status: $body');
    }
  });

  xhr.onError.listen((_) {
    completer.completeError('Finalize: network error');
  });

  xhr.send(formData);
  return completer.future;
}
