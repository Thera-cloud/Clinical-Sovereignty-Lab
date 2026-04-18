// Reusable "Connect Google Calendar" section for client + coach settings.
// Calls the per-user Google Calendar API:
//   GET  /api/calendar/google/connect    -> {oauth_url}
//   GET  /api/calendar/google/status     -> {connected, target_calendar_id, sync_enabled, ...}
//   GET  /api/calendar/google/calendars  -> [{id, summary, primary}, ...]
//   POST /api/calendar/google/settings   -> {target_calendar_id?, sync_enabled?}
//   POST /api/calendar/google/disconnect -> {status}
//   POST /api/calendar/google/sync-now   -> {status}
//
// The "Connect" button opens the OAuth URL in a new browser tab. After the
// user finishes Google's consent flow, the callback closes the popup and the
// section refreshes its state when the user taps "Refresh".
import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher.dart';
import '../config/app_config.dart';

class GoogleCalendarSection extends StatefulWidget {
  final String token;
  final Color gold;
  final Color goldDim;
  final Color textPrimary;
  final Color textSecondary;
  final Color cardBg;

  const GoogleCalendarSection({
    super.key,
    required this.token,
    this.gold = const Color(0xFFC9A962),
    this.goldDim = const Color(0xFF8B7355),
    this.textPrimary = const Color(0xFFE8D5A3),
    this.textSecondary = const Color(0xFF8B7355),
    this.cardBg = const Color(0xFF111111),
  });

  @override
  State<GoogleCalendarSection> createState() => _GoogleCalendarSectionState();
}

class _GoogleCalendarSectionState extends State<GoogleCalendarSection> {
  bool _loading = true;
  bool _connected = false;
  bool _syncEnabled = true;
  String? _targetCalendarId;
  String? _googleEmail;
  String? _lastSyncedAt;
  String? _error;
  List<Map<String, dynamic>> _calendars = [];

  @override
  void initState() {
    super.initState();
    _loadStatus();
  }

  Map<String, String> get _h => {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ${widget.token}',
      };

  Future<void> _loadStatus() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final r = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/calendar/google/status'),
        headers: _h,
      );
      if (r.statusCode == 200) {
        final j = json.decode(r.body) as Map<String, dynamic>;
        setState(() {
          _connected = j['connected'] == true;
          _syncEnabled = j['sync_enabled'] != false;
          _targetCalendarId = j['target_calendar_id']?.toString();
          _googleEmail = j['google_email']?.toString();
          _lastSyncedAt = (j['last_sync_at'] ?? j['last_synced_at'])?.toString();
        });
        if (_connected) {
          await _loadCalendars();
        }
      } else {
        setState(() => _error = 'Status ${r.statusCode}');
      }
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadCalendars() async {
    try {
      final r = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/calendar/google/calendars'),
        headers: _h,
      );
      if (r.statusCode == 200) {
        final decoded = json.decode(r.body);
        final List raw = decoded is List
            ? decoded
            : ((decoded as Map)['calendars'] as List? ?? []);
        final list = raw
            .cast<Map>()
            .map((m) => Map<String, dynamic>.from(m))
            .toList();
        setState(() => _calendars = list);
      }
    } catch (_) {}
  }

  Future<void> _connect() async {
    setState(() => _error = null);
    try {
      final r = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/calendar/google/connect'),
        headers: _h,
      );
      if (r.statusCode == 200) {
        final j = json.decode(r.body) as Map<String, dynamic>;
        final url = j['oauth_url']?.toString() ?? '';
        if (url.isNotEmpty) {
          await launchUrl(
            Uri.parse(url),
            mode: LaunchMode.externalApplication,
            webOnlyWindowName: '_blank',
          );
        } else {
          setState(() => _error = 'No OAuth URL returned');
        }
      } else {
        setState(() => _error = 'Connect failed (${r.statusCode})');
      }
    } catch (e) {
      setState(() => _error = e.toString());
    }
  }

  Future<void> _saveSettings({String? calendarId, bool? syncEnabled}) async {
    setState(() => _error = null);
    try {
      final body = <String, dynamic>{};
      if (calendarId != null) body['target_calendar_id'] = calendarId;
      if (syncEnabled != null) body['sync_enabled'] = syncEnabled;
      final r = await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}/api/calendar/google/settings'),
        headers: _h,
        body: json.encode(body),
      );
      if (r.statusCode == 200) {
        if (calendarId != null) _targetCalendarId = calendarId;
        if (syncEnabled != null) _syncEnabled = syncEnabled;
        if (mounted) setState(() {});
      } else {
        setState(() => _error = 'Save failed (${r.statusCode})');
      }
    } catch (e) {
      setState(() => _error = e.toString());
    }
  }

  Future<void> _syncNow() async {
    setState(() => _error = null);
    try {
      final r = await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}/api/calendar/google/sync-now'),
        headers: _h,
      );
      if (r.statusCode != 200) {
        setState(() => _error = 'Sync failed (${r.statusCode})');
      } else {
        await _loadStatus();
      }
    } catch (e) {
      setState(() => _error = e.toString());
    }
  }

  Future<void> _disconnect() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: widget.cardBg,
        title: const Text('Disconnect Google Calendar?',
            style: TextStyle(color: Color(0xFFC9A962))),
        content: const Text(
            'Future Sanctuary sessions will no longer push to Google. '
            'Existing Google events will remain.',
            style: TextStyle(color: Colors.white)),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Cancel')),
          TextButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Disconnect',
                  style: TextStyle(color: Colors.redAccent))),
        ],
      ),
    );
    if (ok != true) return;
    try {
      final r = await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}/api/calendar/google/disconnect'),
        headers: _h,
      );
      if (r.statusCode == 200) {
        setState(() {
          _connected = false;
          _targetCalendarId = null;
          _googleEmail = null;
          _calendars = [];
        });
      } else {
        setState(() => _error = 'Disconnect failed (${r.statusCode})');
      }
    } catch (e) {
      setState(() => _error = e.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 8),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: widget.cardBg,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: widget.goldDim.withOpacity(0.4)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Icon(Icons.event_available, color: widget.gold, size: 20),
            const SizedBox(width: 8),
            Text('GOOGLE CALENDAR',
                style: TextStyle(
                    color: widget.gold,
                    fontWeight: FontWeight.bold,
                    fontSize: 13,
                    letterSpacing: 1.2)),
            const Spacer(),
            IconButton(
              icon: Icon(Icons.refresh, color: widget.gold, size: 18),
              tooltip: 'Refresh',
              onPressed: _loading ? null : _loadStatus,
            ),
          ]),
          const SizedBox(height: 8),
          if (_loading)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 10),
              child: Center(
                  child: SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                          strokeWidth: 2, color: Color(0xFFC9A962)))),
            )
          else if (!_connected) ...[
            Text(
              'Sync your sessions both ways with Google Calendar. '
              'Events you create here appear in Google. Busy times in Google '
              'block clients from booking you.',
              style: TextStyle(color: widget.textSecondary, fontSize: 12),
            ),
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                style: ElevatedButton.styleFrom(
                  backgroundColor: widget.gold,
                  padding: const EdgeInsets.symmetric(vertical: 12),
                ),
                icon: const Icon(Icons.link, color: Colors.black, size: 18),
                label: const Text('Connect Google Calendar',
                    style: TextStyle(color: Colors.black, fontWeight: FontWeight.w600)),
                onPressed: _connect,
              ),
            ),
          ] else ...[
            _row('Account', _googleEmail ?? '—'),
            _row('Last sync', _lastSyncedAt ?? 'never'),
            const SizedBox(height: 8),
            Text('Target calendar',
                style: TextStyle(color: widget.textSecondary, fontSize: 11)),
            const SizedBox(height: 4),
            DropdownButton<String>(
              value: _calendars.any((c) => c['id'] == _targetCalendarId)
                  ? _targetCalendarId
                  : (_calendars.isNotEmpty ? _calendars.first['id']?.toString() : null),
              isExpanded: true,
              dropdownColor: widget.cardBg,
              style: TextStyle(color: widget.textPrimary, fontSize: 13),
              items: _calendars
                  .map((c) => DropdownMenuItem<String>(
                        value: c['id']?.toString(),
                        child: Text(
                          c['summary']?.toString() ?? c['id']?.toString() ?? '?',
                          overflow: TextOverflow.ellipsis,
                        ),
                      ))
                  .toList(),
              onChanged: (v) {
                if (v != null) _saveSettings(calendarId: v);
              },
            ),
            const SizedBox(height: 8),
            SwitchListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              title: Text('Sync enabled',
                  style: TextStyle(color: widget.textPrimary, fontSize: 13)),
              subtitle: Text(
                'Push Sanctuary sessions to Google + pull busy times back.',
                style: TextStyle(color: widget.textSecondary, fontSize: 11),
              ),
              value: _syncEnabled,
              activeColor: widget.gold,
              onChanged: (v) => _saveSettings(syncEnabled: v),
            ),
            const SizedBox(height: 4),
            Row(children: [
              Expanded(
                child: OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(
                    foregroundColor: widget.gold,
                    side: BorderSide(color: widget.goldDim),
                  ),
                  icon: const Icon(Icons.sync, size: 16),
                  label: const Text('Sync now'),
                  onPressed: _syncNow,
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: TextButton.icon(
                  icon: const Icon(Icons.link_off,
                      size: 16, color: Colors.redAccent),
                  label: const Text('Disconnect',
                      style: TextStyle(color: Colors.redAccent)),
                  onPressed: _disconnect,
                ),
              ),
            ]),
          ],
          if (_error != null) ...[
            const SizedBox(height: 8),
            Text(_error!,
                style: const TextStyle(color: Colors.redAccent, fontSize: 11)),
          ],
        ],
      ),
    );
  }

  Widget _row(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          SizedBox(
              width: 90,
              child: Text(label,
                  style: TextStyle(color: widget.textSecondary, fontSize: 11))),
          Expanded(
              child: Text(value,
                  style: TextStyle(color: widget.textPrimary, fontSize: 12),
                  overflow: TextOverflow.ellipsis)),
        ],
      ),
    );
  }
}
