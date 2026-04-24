/// Direct browser-to-R2 multipart upload for very large classroom videos.
///
/// Why this exists:
///   The legacy `/api/classroom/upload-video` endpoint loads the whole
///   file into memory on both ends — it caps at 500 MB, dies at the
///   browser's ArrayBuffer limit, and gets truncated by Cloudflare's
///   100 MB proxy upload limit. None of those constraints apply when
///   the browser PUTs presigned chunks directly to R2's storage host.
///
/// Flow:
///   1. POST /api/classroom/upload-video/init {filename, size, ...}
///        → backend creates an S3-multipart upload on R2 and returns
///          one presigned PUT URL per 8 MiB part.
///   2. For each part: read [start, end) via Blob.slice (web) or
///      RandomAccessFile.read (native), PUT to its URL, capture ETag.
///   3. POST /api/classroom/upload-video/complete {video_id, parts:[…]}
///        → backend finalizes the multipart upload and kicks off
///          background analysis.
///   4. On any failure / cancel, POST /api/classroom/upload-video/abort.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import '_large_video_picker_stub.dart'
    if (dart.library.html) '_large_video_picker_web.dart'
    if (dart.library.io) '_large_video_picker_io.dart';

export '_large_video_picker_stub.dart'
    if (dart.library.html) '_large_video_picker_web.dart'
    if (dart.library.io) '_large_video_picker_io.dart'
    show PickedLargeVideo, pickLargeVideo;

class LargeVideoUploadResult {
  LargeVideoUploadResult({
    required this.videoId,
    required this.fileSize,
    required this.r2Location,
  });
  final String videoId;
  final int fileSize;
  final String r2Location;
}

class LargeVideoUploadException implements Exception {
  LargeVideoUploadException(this.message);
  final String message;
  @override
  String toString() => 'LargeVideoUploadException: $message';
}

/// Upload a previously-picked video directly to Cloudflare R2 using the
/// backend's presigned-multipart endpoints.
///
/// `apiBaseUrl` is the backend origin (e.g. `https://api.sovereignsanctuary.net`).
/// `bearerToken` is the user's auth bearer for the /init and /complete calls
/// — the per-part PUTs to R2 don't need an auth header (the URL is signed).
Future<LargeVideoUploadResult> uploadLargeVideoDirectToR2({
  required PickedLargeVideo file,
  required String apiBaseUrl,
  required String bearerToken,
  required String coachId,
  required String clientId,
  String familyId = '',
  String description = '',
  void Function(double progress)? onProgress,
  http.Client? httpClient,
}) async {
  final client = httpClient ?? http.Client();
  final ownsClient = httpClient == null;

  String? videoId;
  try {
    // Step 1 — init
    final initResp = await client.post(
      Uri.parse('$apiBaseUrl/api/classroom/upload-video/init'),
      headers: {
        'Content-Type': 'application/json',
        if (bearerToken.isNotEmpty) 'Authorization': 'Bearer $bearerToken',
      },
      body: jsonEncode({
        'coach_id': coachId,
        'client_id': clientId,
        'family_id': familyId,
        'description': description,
        'filename': file.name,
        'content_type': file.contentType,
        'file_size': file.size,
      }),
    );
    if (initResp.statusCode < 200 || initResp.statusCode >= 300) {
      throw LargeVideoUploadException(
        'init failed: HTTP ${initResp.statusCode}: ${initResp.body}',
      );
    }
    final initData = jsonDecode(initResp.body) as Map<String, dynamic>;
    videoId = initData['video_id'] as String;
    final partSize = (initData['part_size'] as num).toInt();
    final totalParts = (initData['total_parts'] as num).toInt();
    final parts = (initData['parts'] as List).cast<Map<String, dynamic>>();

    if (parts.length != totalParts) {
      throw LargeVideoUploadException(
        'init returned ${parts.length} part URLs but total_parts=$totalParts',
      );
    }

    // Step 2 — PUT each part directly to R2.
    // Sequential to keep memory pressure (one chunk in flight) and
    // network behaviour predictable on a coach's home connection.
    final completedParts = <Map<String, dynamic>>[];
    for (int i = 0; i < totalParts; i++) {
      final partNumber = parts[i]['part_number'] as int;
      final url = parts[i]['url'] as String;
      final start = i * partSize;
      final end = (start + partSize > file.size) ? file.size : start + partSize;

      final chunk = await file.readChunk(start, end);
      final etag = await _putPartWithRetry(
        client: client,
        url: url,
        body: chunk,
        partNumber: partNumber,
        maxAttempts: 3,
      );
      completedParts.add({'PartNumber': partNumber, 'ETag': etag});

      if (onProgress != null) {
        // Report after each completed part. 8 MiB granularity → fine
        // enough for 3 GB uploads (375 ticks).
        onProgress((i + 1) / totalParts);
      }
    }

    // Step 3 — complete
    final completeResp = await client.post(
      Uri.parse('$apiBaseUrl/api/classroom/upload-video/complete'),
      headers: {
        'Content-Type': 'application/json',
        if (bearerToken.isNotEmpty) 'Authorization': 'Bearer $bearerToken',
      },
      body: jsonEncode({'video_id': videoId, 'parts': completedParts}),
    );
    if (completeResp.statusCode < 200 || completeResp.statusCode >= 300) {
      throw LargeVideoUploadException(
        'complete failed: HTTP ${completeResp.statusCode}: ${completeResp.body}',
      );
    }
    final completeData = jsonDecode(completeResp.body) as Map<String, dynamic>;
    return LargeVideoUploadResult(
      videoId: videoId,
      fileSize: file.size,
      r2Location: (completeData['r2_location'] ?? '').toString(),
    );
  } catch (e) {
    if (videoId != null) {
      // Best-effort abort so R2 doesn't keep paying for staged parts.
      try {
        await client.post(
          Uri.parse('$apiBaseUrl/api/classroom/upload-video/abort'),
          headers: {
            'Content-Type': 'application/json',
            if (bearerToken.isNotEmpty)
              'Authorization': 'Bearer $bearerToken',
          },
          body: jsonEncode({'video_id': videoId}),
        );
      } catch (_) {/* ignore — already failing */}
    }
    rethrow;
  } finally {
    file.dispose();
    if (ownsClient) client.close();
  }
}

Future<String> _putPartWithRetry({
  required http.Client client,
  required String url,
  required Uint8List body,
  required int partNumber,
  required int maxAttempts,
}) async {
  Object? lastErr;
  for (int attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      final resp = await client.put(
        Uri.parse(url),
        headers: const {'Content-Type': 'application/octet-stream'},
        body: body,
      );
      if (resp.statusCode < 200 || resp.statusCode >= 300) {
        throw LargeVideoUploadException(
          'part $partNumber PUT returned HTTP ${resp.statusCode}: '
          '${resp.body.length > 240 ? resp.body.substring(0, 240) : resp.body}',
        );
      }
      // The S3/R2 spec returns the part's ETag in the response header.
      // The browser will only expose it to JS if the bucket's CORS
      // includes "ETag" in Access-Control-Expose-Headers.
      final etag = resp.headers['etag'];
      if (etag == null || etag.isEmpty) {
        throw LargeVideoUploadException(
          'part $partNumber: ETag header missing from R2 response. '
          'Verify the R2 bucket CORS rules expose ETag.',
        );
      }
      return etag;
    } catch (e) {
      lastErr = e;
      if (attempt < maxAttempts) {
        // Small backoff: 500 ms, 1500 ms.
        await Future.delayed(Duration(milliseconds: 500 * (attempt * attempt)));
        continue;
      }
    }
  }
  throw LargeVideoUploadException(
    'part $partNumber failed after $maxAttempts attempts: $lastErr',
  );
}
