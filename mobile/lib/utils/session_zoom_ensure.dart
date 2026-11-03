import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config/app_config.dart';
import '../services/checkout_launcher.dart';
import 'session_calendar_links.dart';

/// POST /api/sessions/{id}/zoom/ensure then open join (client) or host (coach).
class SessionZoomEnsure {
  static Future<Map<String, String>> fetch({
    required String sessionId,
    required String token,
  }) async {
    if (sessionId.isEmpty || token.isEmpty) return {};
    try {
      final resp = await http
          .post(
            Uri.parse('${AppConfig.apiBaseUrl}/api/sessions/$sessionId/zoom/ensure'),
            headers: {'Authorization': 'Bearer $token'},
          )
          .timeout(const Duration(seconds: 25));
      if (resp.statusCode < 200 || resp.statusCode >= 300) return {};
      final decoded = jsonDecode(resp.body);
      if (decoded is! Map) return {};
      final session = decoded['session'];
      String pick(String key) {
        if (session is Map && session[key] != null) {
          return session[key].toString();
        }
        return (decoded[key] ?? '').toString();
      }

      return {
        'zoom_link': pick('zoom_link'),
        'zoom_host_url': pick('zoom_host_url'),
        'zoom_meeting_id': pick('zoom_meeting_id'),
      };
    } catch (_) {
      return {};
    }
  }

  static Future<bool> launch({
    required String sessionId,
    required String token,
    String fallbackJoin = '',
    String fallbackHost = '',
    bool asHost = false,
  }) async {
    final got = await fetch(sessionId: sessionId, token: token);
    final host = (got['zoom_host_url'] ?? '').toString();
    final join = SessionCalendarLinks.safeJoinUrl(
      (got['zoom_link'] ?? '').toString().isNotEmpty
          ? (got['zoom_link'] ?? '')
          : fallbackJoin,
    );
    final url = asHost
        ? (host.isNotEmpty
            ? host
            : (join.isNotEmpty ? join : SessionCalendarLinks.safeJoinUrl(fallbackJoin)))
        : (join.isNotEmpty ? join : SessionCalendarLinks.safeJoinUrl(fallbackJoin));
    if (url.isEmpty && fallbackHost.isNotEmpty && asHost) {
      return launchCheckoutUrl(fallbackHost);
    }
    if (url.isEmpty) return false;
    return launchCheckoutUrl(url);
  }
}
