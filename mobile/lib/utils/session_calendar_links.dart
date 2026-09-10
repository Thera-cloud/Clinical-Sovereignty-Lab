import 'package:url_launcher/url_launcher.dart';

/// Client add-to-calendar helpers. Join Zoom stays a separate action.
class SessionCalendarLinks {
  static String safeJoinUrl(String raw) {
    final u = raw.trim();
    if (u.isEmpty) return '';
    final lower = u.toLowerCase();
    if (lower.contains('zoom.us/s/') || lower.contains('zak=')) return '';
    if (lower.contains('zoom.us/j/') || lower.contains('zoom.us/wc/')) return u;
    return u.startsWith('https://') ? u : '';
  }

  static String joinFromHostUrl(String host) {
    final match = RegExp(r'zoom\.us/(?:s|j|wc)/(\d+)', caseSensitive: false)
        .firstMatch(host);
    if (match == null) return '';
    return 'https://zoom.us/j/${match.group(1)}';
  }

  static String _icsStamp(DateTime dt) {
    final u = dt.toUtc();
    String two(int n) => n.toString().padLeft(2, '0');
    return '${u.year}${two(u.month)}${two(u.day)}T${two(u.hour)}${two(u.minute)}${two(u.second)}Z';
  }

  static Uri googleTemplate({
    required String summary,
    required DateTime start,
    required DateTime end,
    required String details,
  }) {
    return Uri.https('calendar.google.com', '/calendar/render', {
      'action': 'TEMPLATE',
      'text': summary,
      'dates': '${_icsStamp(start)}/${_icsStamp(end)}',
      'details': details,
      'location': 'Sovereign Sanctuary session',
    });
  }

  static Uri outlookTemplate({
    required String summary,
    required DateTime start,
    required DateTime end,
    required String details,
  }) {
    return Uri.https('outlook.live.com', '/calendar/0/deeplink/compose', {
      'subject': summary,
      'startdt': start.toUtc().toIso8601String(),
      'enddt': end.toUtc().toIso8601String(),
      'body': details,
      'location': 'Sovereign Sanctuary session',
      'path': '/calendar/action/compose',
      'rru': 'addevent',
    });
  }

  static Future<void> open(Uri uri) async {
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
  }
}
