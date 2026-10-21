/// Session clocks use the stored profile zone, not the device or VPN zone.

const Map<String, String> _zoneAbbrev = {
  'ET': 'America/New_York',
  'EST': 'America/New_York',
  'EDT': 'America/New_York',
  'CT': 'America/Chicago',
  'CST': 'America/Chicago',
  'CDT': 'America/Chicago',
  'MT': 'America/Denver',
  'MST': 'America/Denver',
  'MDT': 'America/Denver',
  'PT': 'America/Los_Angeles',
  'PST': 'America/Los_Angeles',
  'PDT': 'America/Los_Angeles',
  'UTC': 'UTC',
  'GMT': 'UTC',
};

const Map<String, int> _stdOffset = {
  'America/New_York': -5,
  'America/Chicago': -6,
  'America/Denver': -7,
  'America/Phoenix': -7,
  'America/Los_Angeles': -8,
  'UTC': 0,
};

String canonicalProfileZone(String raw) {
  final trimmed = raw.trim();
  if (trimmed.isEmpty) return '';
  final mapped = _zoneAbbrev[trimmed.toUpperCase()];
  if (mapped != null) return mapped;
  if (_stdOffset.containsKey(trimmed)) return trimmed;
  return '';
}

DateTime _nthSundayUtc(int year, int month, int n) {
  final first = DateTime.utc(year, month, 1);
  final daysUntilSunday = (DateTime.sunday - first.weekday) % 7;
  return DateTime.utc(year, month, 1 + daysUntilSunday + (n - 1) * 7);
}

bool _inUsDst(DateTime utc, int stdOffset) {
  final start = _nthSundayUtc(utc.year, 3, 2).add(Duration(hours: 2 - stdOffset));
  final end = _nthSundayUtc(utc.year, 11, 1).add(Duration(hours: 1 - stdOffset));
  return !utc.isBefore(start) && utc.isBefore(end);
}

int? _offsetHours(String zone, DateTime utc) {
  if (zone == 'UTC') return 0;
  if (zone == 'America/Phoenix') return -7;
  final std = _stdOffset[zone];
  if (std == null) return null;
  return _inUsDst(utc, std) ? std + 1 : std;
}

String _abbr(String zone, bool dst) {
  switch (zone) {
    case 'America/New_York':
      return dst ? 'EDT' : 'EST';
    case 'America/Chicago':
      return dst ? 'CDT' : 'CST';
    case 'America/Denver':
      return dst ? 'MDT' : 'MST';
    case 'America/Phoenix':
      return 'MST';
    case 'America/Los_Angeles':
      return dst ? 'PDT' : 'PST';
    case 'UTC':
      return 'UTC';
  }
  return '';
}

/// "9:00 AM MDT" in [zoneRaw]. Empty when the zone is unknown.
String formatProfileClock(String iso, String zoneRaw) {
  final zone = canonicalProfileZone(zoneRaw);
  if (zone.isEmpty || iso.trim().isEmpty) return '';
  DateTime utc;
  try {
    utc = DateTime.parse(iso).toUtc();
  } catch (_) {
    return '';
  }
  final off = _offsetHours(zone, utc);
  if (off == null) return '';
  final local = utc.add(Duration(hours: off));
  final std = _stdOffset[zone] ?? 0;
  final dst = zone != 'UTC' && zone != 'America/Phoenix' && _inUsDst(utc, std);
  var hour = local.hour;
  final ap = hour >= 12 ? 'PM' : 'AM';
  hour = hour % 12;
  if (hour == 0) hour = 12;
  final minute = local.minute.toString().padLeft(2, '0');
  return '$hour:$minute $ap ${_abbr(zone, dst)}';
}
