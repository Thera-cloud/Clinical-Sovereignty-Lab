// Coach Workspace OAuth (GOOGLE_WS_*). Separate from GoogleCalendarSection (183).
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher.dart';
import '../config/app_config.dart';

class GoogleWorkspaceSection extends StatefulWidget {
  final String token;
  final Color gold;
  final Color goldDim;
  final Color textPrimary;
  final Color textSecondary;
  final Color cardBg;
  /// Hub tab: show waiting-O9 copy instead of shrinking when flag is off.
  final bool forceShow;

  const GoogleWorkspaceSection({
    super.key,
    required this.token,
    this.gold = const Color(0xFFC9A962),
    this.goldDim = const Color(0xFF8B7355),
    this.textPrimary = const Color(0xFFE8D5A3),
    this.textSecondary = const Color(0xFF8B7355),
    this.cardBg = const Color(0xFF111111),
    this.forceShow = false,
  });

  @override
  State<GoogleWorkspaceSection> createState() => _GoogleWorkspaceSectionState();
}

class _GoogleWorkspaceSectionState extends State<GoogleWorkspaceSection> {
  bool _loading = true;
  bool _visible = false;
  bool _connected = false;
  String? _googleEmail;
  String? _error;

  Map<String, String> get _h => {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ${widget.token}',
      };

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final health = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/workspace/google/health'),
        headers: _h,
      );
      if (health.statusCode != 200) {
        setState(() {
          _visible = false;
          _loading = false;
        });
        return;
      }
      final hj = json.decode(health.body) as Map<String, dynamic>;
      final visible = hj['connect_visible'] == true;
      if (!visible && !widget.forceShow) {
        setState(() {
          _visible = false;
          _loading = false;
        });
        return;
      }
      final st = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/workspace/google/status'),
        headers: _h,
      );
      String? email;
      var connected = false;
      if (st.statusCode == 200) {
        final sj = json.decode(st.body) as Map<String, dynamic>;
        connected = sj['connected'] == true;
        email = sj['google_email']?.toString();
      }
      if (!mounted) return;
      setState(() {
        _visible = true;
        _connected = connected;
        _googleEmail = email;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  Future<void> _connect() async {
    setState(() => _error = null);
    try {
      final r = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/workspace/google/connect'),
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

  @override
  Widget build(BuildContext context) {
    if (!_loading && !_visible && !widget.forceShow) return const SizedBox.shrink();
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
            Icon(Icons.cloud_outlined, color: widget.gold, size: 20),
            const SizedBox(width: 8),
            Text('GOOGLE WORKSPACE',
                style: TextStyle(
                    color: widget.gold,
                    fontWeight: FontWeight.bold,
                    fontSize: 13,
                    letterSpacing: 1.2)),
            const Spacer(),
            IconButton(
              icon: Icon(Icons.refresh, color: widget.gold, size: 18),
              tooltip: 'Refresh',
              onPressed: _loading ? null : _load,
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
          else if (_connected) ...[
            Text('Account', style: TextStyle(color: widget.textSecondary, fontSize: 11)),
            const SizedBox(height: 4),
            Text(_googleEmail ?? '—',
                style: TextStyle(color: widget.textPrimary, fontSize: 13)),
          ] else if (!_visible) ...[
            Text(
              'Connect Google Workspace is hidden until Google verification (O9). '
              'Calendar Sync above stays available. Test users only before then.',
              style: TextStyle(color: widget.textSecondary, fontSize: 12),
            ),
          ] else ...[
            Text(
              'Grant Calendar, Gmail drafts, and Drive for this coach mailbox. '
              'This is not the Calendar Sync connection above.',
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
                label: const Text('Connect Google Workspace',
                    style: TextStyle(color: Colors.black, fontWeight: FontWeight.w600)),
                onPressed: _connect,
              ),
            ),
          ],
          if (_error != null) ...[
            const SizedBox(height: 8),
            Text(_error!, style: const TextStyle(color: Colors.redAccent, fontSize: 12)),
          ],
        ],
      ),
    );
  }
}
