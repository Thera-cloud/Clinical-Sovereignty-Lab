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
  bool _lethalMeans = false;
  bool _lethalFlagOn = false;
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
          _lethalMeans = d['lethal_means_guidance_ok'] == true;
          _lethalFlagOn = d['lethal_means_flag_enabled'] == true;
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
      final body = <String, dynamic>{
        'population': _pop,
        'population_shielded': _pop != 'general',
        'family_concern_consent': _consent,
      };
      if (_lethalFlagOn) {
        body['lethal_means_guidance_ok'] = _lethalMeans;
      }
      final resp = await http.put(
        uri,
        headers: _authHeaders(widget.profile),
        body: jsonEncode(body),
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
          if (_lethalFlagOn)
            SwitchListTile(
              value: _lethalMeans,
              activeColor: _HR.gold,
              title: const Text(
                'Allow voluntary secure-storage framing (never confiscation)',
                style: TextStyle(color: _HR.text, fontSize: 13),
              ),
              subtitle: const Text(
                'Only when you opt in. Nate may discuss temporary secure storage of lethal means.',
                style: TextStyle(color: _HR.muted, fontSize: 11),
              ),
              onChanged: (v) => setState(() => _lethalMeans = v),
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
  final _relCtrl = TextEditingController(text: 'spouse');
  List<Map<String, dynamic>> _members = [];
  String? _selectedUsername;
  bool _loading = true;
  bool _sending = false;
  String? _msg;

  @override
  void initState() {
    super.initState();
    _loadMembers();
  }

  Future<void> _loadMembers() async {
    setState(() {
      _loading = true;
      _msg = null;
    });
    try {
      final uri = Uri.parse('${AppConfig.apiBaseUrl}/api/high-risk-crisis/family/members');
      final resp = await http.get(uri, headers: _authHeaders(widget.profile));
      if (resp.statusCode == 200) {
        final d = jsonDecode(resp.body) as Map<String, dynamic>;
        final list = (d['members'] is List) ? List.from(d['members'] as List) : [];
        setState(() {
          _members = list
              .whereType<Map>()
              .map((e) => Map<String, dynamic>.from(e))
              .toList();
          final flaggable = _members.where((m) => m['can_flag'] == true).toList();
          if (flaggable.length == 1) {
            _selectedUsername = flaggable.first['username']?.toString();
          }
          _loading = false;
        });
      } else {
        setState(() {
          _msg = 'Could not load family members (${resp.statusCode})';
          _loading = false;
        });
      }
    } catch (e) {
      setState(() {
        _msg = e.toString();
        _loading = false;
      });
    }
  }

  Future<void> _submit() async {
    final target = (_selectedUsername ?? '').trim();
    if (target.isEmpty) {
      setState(() => _msg = 'Select a family member');
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
    _relCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final flaggable = _members.where((m) => m['can_flag'] == true).toList();
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
            if (_loading)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 24),
                child: Center(child: CircularProgressIndicator(color: _HR.gold)),
              )
            else if (flaggable.isEmpty)
              Text(
                _members.isEmpty
                    ? 'No family members on your account yet.'
                    : 'No family members have opted in to concern flags. Ask them to enable it under Safety & population.',
                style: const TextStyle(color: _HR.text, height: 1.4),
              )
            else
              DropdownButtonFormField<String>(
                value: _selectedUsername,
                dropdownColor: _HR.card,
                style: const TextStyle(color: _HR.text),
                decoration: const InputDecoration(
                  labelText: 'Family member',
                  labelStyle: TextStyle(color: _HR.muted),
                  enabledBorder: UnderlineInputBorder(borderSide: BorderSide(color: _HR.muted)),
                ),
                items: [
                  for (final m in flaggable)
                    DropdownMenuItem(
                      value: m['username']?.toString(),
                      child: Text(
                        '${m['name'] ?? m['username']} (${m['username']})',
                        style: const TextStyle(color: _HR.text),
                      ),
                    ),
                ],
                onChanged: (v) => setState(() => _selectedUsername = v),
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
              onPressed: (_sending || flaggable.isEmpty) ? null : _submit,
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

/// Coach clients-tab entry with active-window badge — QUANTUM-CRYSTAL-ARCH.
class CoachRiskWindowsEntryButton extends StatefulWidget {
  final Map profile;
  const CoachRiskWindowsEntryButton({super.key, required this.profile});

  @override
  State<CoachRiskWindowsEntryButton> createState() => _CoachRiskWindowsEntryButtonState();
}

class _CoachRiskWindowsEntryButtonState extends State<CoachRiskWindowsEntryButton> {
  int _count = 0;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    try {
      final uri = Uri.parse('${AppConfig.apiBaseUrl}/api/high-risk-crisis/coach/risk-windows');
      final resp = await http.get(uri, headers: _authHeaders(widget.profile));
      if (resp.statusCode == 200 && mounted) {
        final d = jsonDecode(resp.body) as Map<String, dynamic>;
        setState(() => _count = (d['count'] is int) ? d['count'] as int : 0);
      }
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    return IconButton(
      tooltip: _count > 0 ? 'Risk windows ($_count active)' : 'Risk windows',
      icon: Badge(
        isLabelVisible: _count > 0,
        label: Text('$_count', style: const TextStyle(fontSize: 10)),
        backgroundColor: const Color(0xFFEF4444),
        child: const Icon(Icons.shield_outlined, color: Color(0xFFEF4444)),
      ),
      onPressed: () async {
        await Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => CoachRiskWindowsScreen(profile: widget.profile),
          ),
        );
        if (mounted) _refresh();
      },
    );
  }
}

/// Coach portal — active risk windows + critical incident + set occupational population.
class CoachRiskWindowsScreen extends StatefulWidget {
  final Map profile;
  const CoachRiskWindowsScreen({super.key, required this.profile});

  @override
  State<CoachRiskWindowsScreen> createState() => _CoachRiskWindowsScreenState();
}

class _CoachRiskWindowsScreenState extends State<CoachRiskWindowsScreen> {
  List<dynamic> _windows = [];
  List<dynamic> _clients = [];
  List<String> _pops = const ['general'];
  String? _error;
  bool _loading = true;
  String? _busyClient;

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
      // ack=1 stamps coach review for P0 SLA (auditor GET omits ack)
      final uri = Uri.parse(
          '${AppConfig.apiBaseUrl}/api/high-risk-crisis/coach/risk-windows?ack=1');
      final resp = await http.get(uri, headers: _authHeaders(widget.profile));
      if (resp.statusCode != 200) {
        setState(() {
          _error = 'Could not load risk windows (${resp.statusCode})';
          _loading = false;
        });
        return;
      }
      final d = jsonDecode(resp.body) as Map<String, dynamic>;
      setState(() {
        _windows = (d['windows'] is List) ? List.from(d['windows'] as List) : [];
        _clients = (d['clients'] is List) ? List.from(d['clients'] as List) : [];
        final pops = d['populations'];
        if (pops is List && pops.isNotEmpty) {
          _pops = pops.map((e) => e.toString()).toList();
        }
        _loading = false;
      });
    } catch (e) {
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  Future<void> _openCritical(String username) async {
    setState(() => _busyClient = username);
    try {
      final uri = Uri.parse('${AppConfig.apiBaseUrl}/api/high-risk-crisis/coach/critical-incident');
      final resp = await http.post(
        uri,
        headers: _authHeaders(widget.profile),
        body: jsonEncode({'client_username': username}),
      );
      if (!mounted) return;
      final ok = resp.statusCode == 200;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(ok ? 'Critical-incident window opened for $username' : 'Failed (${resp.statusCode})'),
        backgroundColor: ok ? _HR.cyan : Colors.redAccent,
      ));
      if (ok) await _load();
    } finally {
      if (mounted) setState(() => _busyClient = null);
    }
  }

  Future<void> _setPopulation(String username, String pop) async {
    setState(() => _busyClient = username);
    try {
      final uri = Uri.parse('${AppConfig.apiBaseUrl}/api/high-risk-crisis/coach/population');
      final resp = await http.put(
        uri,
        headers: _authHeaders(widget.profile),
        body: jsonEncode({
          'client_username': username,
          'population': pop,
          'population_shielded': pop != 'general',
        }),
      );
      if (!mounted) return;
      final ok = resp.statusCode == 200;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(ok ? 'Population set to $pop for $username' : 'Failed (${resp.statusCode})'),
        backgroundColor: ok ? _HR.gold : Colors.redAccent,
      ));
      if (ok) await _load();
    } finally {
      if (mounted) setState(() => _busyClient = null);
    }
  }

  void _pickPopulation(String username, String current) {
    showModalBottomSheet(
      context: context,
      backgroundColor: _HR.card,
      builder: (ctx) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            const Padding(
              padding: EdgeInsets.all(16),
              child: Text('Occupational population (crisis lines)',
                  style: TextStyle(color: _HR.gold, fontWeight: FontWeight.bold)),
            ),
            for (final p in _pops)
              ListTile(
                title: Text(p, style: TextStyle(color: p == current ? _HR.cyan : _HR.text)),
                trailing: p == current ? const Icon(Icons.check, color: _HR.cyan) : null,
                onTap: () {
                  Navigator.pop(ctx);
                  _setPopulation(username, p);
                },
              ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _HR.bg,
      appBar: AppBar(
        backgroundColor: _HR.bg,
        title: const Text('Risk windows', style: TextStyle(color: _HR.gold, fontFamily: 'CormorantGaramond')),
        iconTheme: const IconThemeData(color: _HR.gold),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: _loading ? null : _load),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: _HR.gold))
          : _error != null
              ? Center(child: Text(_error!, style: const TextStyle(color: Colors.redAccent)))
              : RefreshIndicator(
                  onRefresh: _load,
                  color: _HR.gold,
                  child: ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      Text(
                        '${_windows.length} active window${_windows.length == 1 ? '' : 's'}',
                        style: const TextStyle(color: _HR.muted, fontSize: 13),
                      ),
                      const SizedBox(height: 12),
                      if (_windows.isEmpty)
                        const Padding(
                          padding: EdgeInsets.only(bottom: 16),
                          child: Text('No active risk windows. Open one after P0/P1 or a critical incident.',
                              style: TextStyle(color: _HR.text, height: 1.4)),
                        ),
                      for (final w in _windows)
                        if (w is Map)
                          Container(
                            margin: const EdgeInsets.only(bottom: 10),
                            padding: const EdgeInsets.all(14),
                            decoration: BoxDecoration(
                              color: _HR.card,
                              borderRadius: BorderRadius.circular(10),
                              border: Border.all(color: Colors.redAccent.withOpacity(0.35)),
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  (w['client_name'] ?? w['username'] ?? '').toString(),
                                  style: const TextStyle(color: _HR.gold, fontWeight: FontWeight.bold, fontSize: 15),
                                ),
                                const SizedBox(height: 4),
                                Text(
                                  'Reason: ${w['reason'] ?? '—'} · Cadence: ${w['cadence_hours'] ?? '—'}h',
                                  style: const TextStyle(color: _HR.text, fontSize: 13),
                                ),
                                Text(
                                  'Expires: ${w['expires_at'] ?? '—'} · Pop: ${w['population'] ?? 'general'}',
                                  style: const TextStyle(color: _HR.muted, fontSize: 12),
                                ),
                              ],
                            ),
                          ),
                      const SizedBox(height: 8),
                      const Text('Assigned clients', style: TextStyle(color: _HR.gold, fontSize: 14, fontWeight: FontWeight.w600)),
                      const SizedBox(height: 8),
                      for (final c in _clients)
                        if (c is Map)
                          Container(
                            margin: const EdgeInsets.only(bottom: 8),
                            child: ListTile(
                              tileColor: _HR.card,
                              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                              title: Text(
                                (c['name'] ?? c['username'] ?? '').toString(),
                                style: const TextStyle(color: _HR.text, fontSize: 14),
                              ),
                              subtitle: Text(
                                'population: ${c['population'] ?? 'general'}',
                                style: const TextStyle(color: _HR.muted, fontSize: 12),
                              ),
                              trailing: _busyClient == c['username']
                                  ? const SizedBox(
                                      width: 22,
                                      height: 22,
                                      child: CircularProgressIndicator(strokeWidth: 2, color: _HR.gold),
                                    )
                                  : PopupMenuButton<String>(
                                      color: _HR.card,
                                      icon: const Icon(Icons.more_vert, color: _HR.gold),
                                      onSelected: (v) {
                                        final u = (c['username'] ?? '').toString();
                                        if (u.isEmpty) return;
                                        if (v == 'critical') _openCritical(u);
                                        if (v == 'population') {
                                          _pickPopulation(u, (c['population'] ?? 'general').toString());
                                        }
                                      },
                                      itemBuilder: (_) => const [
                                        PopupMenuItem(value: 'critical', child: Text('Open critical-incident window', style: TextStyle(color: Colors.white))),
                                        PopupMenuItem(value: 'population', child: Text('Set occupational population', style: TextStyle(color: Colors.white))),
                                      ],
                                    ),
                            ),
                          ),
                    ],
                  ),
                ),
    );
  }
}
