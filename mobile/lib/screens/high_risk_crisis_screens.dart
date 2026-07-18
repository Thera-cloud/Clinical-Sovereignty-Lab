/// High-risk occupational crisis surfaces — QUANTUM-CRYSTAL-ARCH
/// Confidentiality disclosure, population setup, family concern flag, education.

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../config/app_config.dart';

class _HR {
  static const bg = Color(0xFF050505);
  static const card = Color(0xFF111111);
  static const gold = Color(0xFFC9A962);
  static const text = Color(0xFFE8E8E8);
  static const muted = Color(0xFF8B7355);
  static const cyan = Color(0xFF4ECDC4);
}

Map<String, String> _authHeaders(Map profile) {
  final token = (profile['token'] ?? '').toString();
  return {
    'Content-Type': 'application/json',
    if (token.isNotEmpty) 'Authorization': 'Bearer $token',
  };
}

/// Entry hub from Settings.
class HighRiskCrisisHubScreen extends StatelessWidget {
  final Map profile;
  const HighRiskCrisisHubScreen({super.key, required this.profile});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _HR.bg,
      appBar: AppBar(
        backgroundColor: _HR.bg,
        title: const Text('Safety & population', style: TextStyle(color: _HR.gold, fontFamily: 'CormorantGaramond')),
        iconTheme: const IconThemeData(color: _HR.gold),
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          _tile(context, 'Who can see what you tell Nate', Icons.lock_outline, () {
            Navigator.push(context, MaterialPageRoute(
              builder: (_) => ConfidentialityDisclosureScreen(profile: profile),
            ));
          }),
          _tile(context, 'Population / service background', Icons.badge_outlined, () {
            Navigator.push(context, MaterialPageRoute(
              builder: (_) => PopulationSetupScreen(profile: profile),
            ));
          }),
          _tile(context, 'Family education (kitchen table)', Icons.family_restroom, () {
            Navigator.push(context, MaterialPageRoute(
              builder: (_) => FamilyEducationScreen(profile: profile),
            ));
          }),
          _tile(context, 'Flag concern for a family member', Icons.flag_outlined, () {
            Navigator.push(context, MaterialPageRoute(
              builder: (_) => FamilyConcernFlagScreen(profile: profile),
            ));
          }),
        ],
      ),
    );
  }

  Widget _tile(BuildContext context, String title, IconData icon, VoidCallback onTap) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      child: ListTile(
        tileColor: _HR.card,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        leading: Icon(icon, color: _HR.cyan),
        title: Text(title, style: const TextStyle(color: _HR.text, fontSize: 15)),
        trailing: const Icon(Icons.chevron_right, color: _HR.muted),
        onTap: onTap,
      ),
    );
  }
}

class ConfidentialityDisclosureScreen extends StatefulWidget {
  final Map profile;
  const ConfidentialityDisclosureScreen({super.key, required this.profile});

  @override
  State<ConfidentialityDisclosureScreen> createState() => _ConfidentialityDisclosureScreenState();
}

class _ConfidentialityDisclosureScreenState extends State<ConfidentialityDisclosureScreen> {
  Map<String, dynamic>? _copy;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final uri = Uri.parse('${AppConfig.apiBaseUrl}/api/high-risk-crisis/confidentiality');
      final resp = await http.get(uri, headers: _authHeaders(widget.profile));
      if (resp.statusCode == 200) {
        setState(() => _copy = jsonDecode(resp.body) as Map<String, dynamic>);
      } else {
        setState(() => _error = 'Could not load disclosure (${resp.statusCode})');
      }
    } catch (e) {
      setState(() => _error = e.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _HR.bg,
      appBar: AppBar(
        backgroundColor: _HR.bg,
        title: const Text('Confidentiality', style: TextStyle(color: _HR.gold)),
        iconTheme: const IconThemeData(color: _HR.gold),
      ),
      body: _error != null
          ? Center(child: Text(_error!, style: const TextStyle(color: _HR.muted)))
          : _copy == null
              ? const Center(child: CircularProgressIndicator(color: _HR.gold))
              : Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(_copy!['headline']?.toString() ?? '',
                          style: const TextStyle(color: _HR.gold, fontSize: 22, fontFamily: 'CormorantGaramond')),
                      const SizedBox(height: 16),
                      Text(_copy!['body']?.toString() ?? '',
                          style: const TextStyle(color: _HR.text, height: 1.5, fontSize: 14)),
                      const SizedBox(height: 20),
                      _bullet(_copy!['employer_line']?.toString() ?? ''),
                      _bullet(_copy!['coach_line']?.toString() ?? ''),
                      _bullet(_copy!['legal_line']?.toString() ?? ''),
                    ],
                  ),
                ),
    );
  }

  Widget _bullet(String t) {
    if (t.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('• ', style: TextStyle(color: _HR.cyan)),
          Expanded(child: Text(t, style: const TextStyle(color: _HR.text, fontSize: 13))),
        ],
      ),
    );
  }
}

class PopulationSetupScreen extends StatefulWidget {
  final Map profile;
  const PopulationSetupScreen({super.key, required this.profile});

  @override
  State<PopulationSetupScreen> createState() => _PopulationSetupScreenState();
}

class _PopulationSetupScreenState extends State<PopulationSetupScreen> {
  String _pop = 'general';
  bool _consent = false;
  bool _saving = false;
  String? _msg;

  static const _options = <String, String>{
    'general': 'General',
    'veteran': 'Veteran / service member',
    'first_responder_le': 'First responder — law enforcement',
    'first_responder_fire_ems': 'First responder — fire / EMS',
    'military_family': 'Military / first-responder family',
  };

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final uri = Uri.parse('${AppConfig.apiBaseUrl}/api/high-risk-crisis/population');
      final resp = await http.get(uri, headers: _authHeaders(widget.profile));
      if (resp.statusCode == 200) {
        final d = jsonDecode(resp.body) as Map<String, dynamic>;
        setState(() {
          _pop = (d['population'] ?? 'general').toString();
          _consent = d['family_concern_consent'] == true;
        });
      }
    } catch (_) {}
  }

  Future<void> _save() async {
    setState(() {
      _saving = true;
      _msg = null;
    });
    try {
      final uri = Uri.parse('${AppConfig.apiBaseUrl}/api/high-risk-crisis/population');
      final resp = await http.put(
        uri,
        headers: _authHeaders(widget.profile),
        body: jsonEncode({
          'population': _pop,
          'population_shielded': _pop != 'general',
          'family_concern_consent': _consent,
        }),
      );
      setState(() {
        _msg = resp.statusCode == 200 ? 'Saved.' : 'Save failed (${resp.statusCode})';
      });
    } catch (e) {
      setState(() => _msg = e.toString());
    } finally {
      setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _HR.bg,
      appBar: AppBar(
        backgroundColor: _HR.bg,
        title: const Text('Population', style: TextStyle(color: _HR.gold)),
        iconTheme: const IconThemeData(color: _HR.gold),
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const Text(
            'This sets crisis lines (Veterans Crisis Line, Copline) and employer shielding.',
            style: TextStyle(color: _HR.muted, fontSize: 13),
          ),
          const SizedBox(height: 16),
          ..._options.entries.map((e) => RadioListTile<String>(
                value: e.key,
                groupValue: _pop,
                activeColor: _HR.gold,
                title: Text(e.value, style: const TextStyle(color: _HR.text, fontSize: 14)),
                onChanged: (v) => setState(() => _pop = v ?? 'general'),
              )),
          SwitchListTile(
            value: _consent,
            activeColor: _HR.gold,
            title: const Text(
              'Allow family to flag concern (raises check-ins; no message content shared)',
              style: TextStyle(color: _HR.text, fontSize: 13),
            ),
            onChanged: (v) => setState(() => _consent = v),
          ),
          const SizedBox(height: 12),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: _HR.gold),
            onPressed: _saving ? null : _save,
            child: Text(_saving ? 'Saving…' : 'Save', style: const TextStyle(color: Colors.black)),
          ),
          if (_msg != null) ...[
            const SizedBox(height: 12),
            Text(_msg!, style: const TextStyle(color: _HR.cyan)),
          ],
        ],
      ),
    );
  }
}

class FamilyEducationScreen extends StatefulWidget {
  final Map profile;
  const FamilyEducationScreen({super.key, required this.profile});

  @override
  State<FamilyEducationScreen> createState() => _FamilyEducationScreenState();
}

class _FamilyEducationScreenState extends State<FamilyEducationScreen> {
  List<dynamic> _sections = [];
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final uri = Uri.parse('${AppConfig.apiBaseUrl}/api/high-risk-crisis/family/education');
      final resp = await http.get(uri, headers: _authHeaders(widget.profile));
      if (resp.statusCode == 200) {
        final d = jsonDecode(resp.body) as Map<String, dynamic>;
        setState(() => _sections = (d['sections'] as List?) ?? []);
      } else {
        setState(() => _error = 'Load failed (${resp.statusCode})');
      }
    } catch (e) {
      setState(() => _error = e.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _HR.bg,
      appBar: AppBar(
        backgroundColor: _HR.bg,
        title: const Text('Family education', style: TextStyle(color: _HR.gold)),
        iconTheme: const IconThemeData(color: _HR.gold),
      ),
      body: _error != null
          ? Center(child: Text(_error!, style: const TextStyle(color: _HR.muted)))
          : _sections.isEmpty
              ? const Center(child: CircularProgressIndicator(color: _HR.gold))
              : ListView.builder(
                  padding: const EdgeInsets.all(20),
                  itemCount: _sections.length,
                  itemBuilder: (_, i) {
                    final s = _sections[i] as Map<String, dynamic>;
                    return Container(
                      margin: const EdgeInsets.only(bottom: 16),
                      padding: const EdgeInsets.all(16),
                      decoration: BoxDecoration(color: _HR.card, borderRadius: BorderRadius.circular(8)),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(s['title']?.toString() ?? '',
                              style: const TextStyle(color: _HR.gold, fontSize: 16, fontWeight: FontWeight.w600)),
                          const SizedBox(height: 8),
                          Text(s['body']?.toString() ?? '',
                              style: const TextStyle(color: _HR.text, height: 1.45, fontSize: 13)),
                        ],
                      ),
                    );
                  },
                ),
    );
  }
}

class FamilyConcernFlagScreen extends StatefulWidget {
  final Map profile;
  const FamilyConcernFlagScreen({super.key, required this.profile});

  @override
  State<FamilyConcernFlagScreen> createState() => _FamilyConcernFlagScreenState();
}

class _FamilyConcernFlagScreenState extends State<FamilyConcernFlagScreen> {
  final _targetCtrl = TextEditingController();
  final _relCtrl = TextEditingController(text: 'spouse');
  bool _sending = false;
  String? _msg;

  Future<void> _submit() async {
    final target = _targetCtrl.text.trim();
    if (target.isEmpty) {
      setState(() => _msg = 'Enter the family member username');
      return;
    }
    setState(() {
      _sending = true;
      _msg = null;
    });
    try {
      final uri = Uri.parse('${AppConfig.apiBaseUrl}/api/high-risk-crisis/family/concern-flag');
      final resp = await http.post(
        uri,
        headers: _authHeaders(widget.profile),
        body: jsonEncode({
          'target_username': target,
          'relationship': _relCtrl.text.trim().isEmpty ? 'family' : _relCtrl.text.trim(),
        }),
      );
      if (resp.statusCode == 200) {
        setState(() => _msg =
            'Concern flagged. Nate will check in sooner. Conversation content was not shared.');
      } else {
        setState(() => _msg = 'Failed: ${resp.body}');
      }
    } catch (e) {
      setState(() => _msg = e.toString());
    } finally {
      setState(() => _sending = false);
    }
  }

  @override
  void dispose() {
    _targetCtrl.dispose();
    _relCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _HR.bg,
      appBar: AppBar(
        backgroundColor: _HR.bg,
        title: const Text('Flag concern', style: TextStyle(color: _HR.gold)),
        iconTheme: const IconThemeData(color: _HR.gold),
      ),
      body: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Raises check-in attentiveness for your family member. Does not share what either of you said to Nate. They must have consented in Population settings.',
              style: TextStyle(color: _HR.muted, fontSize: 13, height: 1.4),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _targetCtrl,
              style: const TextStyle(color: _HR.text),
              decoration: const InputDecoration(
                labelText: 'Their username',
                labelStyle: TextStyle(color: _HR.muted),
                enabledBorder: UnderlineInputBorder(borderSide: BorderSide(color: _HR.muted)),
              ),
            ),
            TextField(
              controller: _relCtrl,
              style: const TextStyle(color: _HR.text),
              decoration: const InputDecoration(
                labelText: 'Your relationship',
                labelStyle: TextStyle(color: _HR.muted),
                enabledBorder: UnderlineInputBorder(borderSide: BorderSide(color: _HR.muted)),
              ),
            ),
            const SizedBox(height: 20),
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: _HR.gold),
              onPressed: _sending ? null : _submit,
              child: Text(_sending ? 'Sending…' : 'Flag concern', style: const TextStyle(color: Colors.black)),
            ),
            if (_msg != null) ...[
              const SizedBox(height: 16),
              Text(_msg!, style: const TextStyle(color: _HR.cyan, fontSize: 13)),
            ],
          ],
        ),
      ),
    );
  }
}
