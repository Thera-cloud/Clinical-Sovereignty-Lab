import 'dart:convert';

import 'package:flutter/foundation.dart' show kIsWeb, debugPrint;
import 'package:http/http.dart' as http;

import '../config/app_config.dart';
import 'local_history_service.dart';

/// Pull server retention tombstones and prune local SQLite.
///
/// No-op on Flutter web (SQLite disabled) and when [token] is empty.
/// Non-cohort users receive zero conversation_history tombstones, so
/// this never deletes their local history.
Future<void> syncDataTombstones(String token) async {
  if (kIsWeb) return;
  final tok = token.trim();
  if (tok.isEmpty) return;
  try {
    final uri = Uri.parse('${AppConfig.apiBaseUrl}/api/client/data-tombstones');
    final resp = await http
        .get(uri, headers: {'Authorization': 'Bearer $tok'})
        .timeout(const Duration(seconds: 12));
    if (resp.statusCode != 200) return;
    final body = jsonDecode(resp.body);
    if (body is! Map) return;
    final raw = body['tombstones'];
    if (raw is! List || raw.isEmpty) return;
    final hasChatTombstone = raw.any((t) {
      if (t is! Map) return false;
      return (t['table'] ?? '').toString() == 'conversation_history';
    });
    if (!hasChatTombstone) return;
    final cutoff = DateTime.now()
        .toUtc()
        .subtract(const Duration(days: 30))
        .toIso8601String();
    await LocalHistoryService.instance.deleteOlderThan(cutoff);
  } catch (e) {
    debugPrint('[tombstone_sync] skip: $e');
  }
}
