import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import '../config/app_config.dart';

class FamilyConstellationScreen extends StatefulWidget {
  final Map<String, dynamic> profile;
  const FamilyConstellationScreen({super.key, required this.profile});

  @override
  State<FamilyConstellationScreen> createState() => _FamilyConstellationState();
}

class _FamilyConstellationState extends State<FamilyConstellationScreen> {
  List<Map<String, dynamic>> _members = [];
  List<Map<String, dynamic>> _heritage = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final token = widget.profile['token'] ?? '';
    final headers = {'Authorization': 'Bearer $token'};
    try {
      final cResp = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/sse-client/family/constellation'),
        headers: headers,
      ).timeout(const Duration(seconds: 8));
      if (cResp.statusCode == 200) {
        final data = json.decode(cResp.body);
        _members = List<Map<String, dynamic>>.from(data['members'] ?? []);
      }
      final hResp = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/sse-client/family/heritage'),
        headers: headers,
      ).timeout(const Duration(seconds: 8));
      if (hResp.statusCode == 200) {
        final data = json.decode(hResp.body);
        _heritage = List<Map<String, dynamic>>.from(data['landmarks'] ?? []);
      }
    } catch (_) {}
    if (mounted) setState(() => _loading = false);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF050505),
      appBar: AppBar(
        backgroundColor: const Color(0xFF0A0A0A),
        title: const Text('Family Constellation',
            style: TextStyle(fontFamily: 'Cormorant Garamond', color: Color(0xFFC9A962))),
        iconTheme: const IconThemeData(color: Color(0xFFC9A962)),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: Color(0xFFC9A962)))
          : _members.isEmpty
              ? const Center(child: Text('No family linked yet.',
                  style: TextStyle(color: Color(0xFF888888))))
              : ListView(padding: const EdgeInsets.all(16), children: [
                  ..._members.map(_memberTile),
                  if (_heritage.isNotEmpty) ...[
                    const SizedBox(height: 24),
                    const Text('Heritage Landmarks',
                        style: TextStyle(color: Color(0xFFC9A962), fontSize: 16,
                            fontFamily: 'Cormorant Garamond')),
                    const SizedBox(height: 8),
                    ..._heritage.map(_heritageTile),
                  ],
                ]),
    );
  }

  Widget _memberTile(Map<String, dynamic> m) {
    final name = m['display_name'] ?? m['user_id'] ?? 'Member';
    final biome = (m['current_biome'] ?? 'unknown').toString().replaceAll('_', ' ');
    final gated = m['age_gated'] == true;
    return Card(
      color: const Color(0xFF111111),
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        leading: Icon(gated ? Icons.child_care : Icons.person,
            color: gated ? const Color(0xFF4ECDC4) : const Color(0xFFC9A962)),
        title: Text(name, style: const TextStyle(color: Colors.white)),
        subtitle: Text('Biome: $biome', style: const TextStyle(color: Color(0xFF888888), fontSize: 12)),
      ),
    );
  }

  Widget _heritageTile(Map<String, dynamic> h) {
    return Card(
      color: const Color(0xFF111111),
      margin: const EdgeInsets.only(bottom: 6),
      child: ListTile(
        leading: const Icon(Icons.auto_awesome, color: Color(0xFF9D4EDD), size: 20),
        title: Text(h['label'] ?? '', style: const TextStyle(color: Colors.white, fontSize: 13)),
        subtitle: Text(h['description'] ?? '', style: const TextStyle(color: Color(0xFF888888), fontSize: 11)),
      ),
    );
  }
}
