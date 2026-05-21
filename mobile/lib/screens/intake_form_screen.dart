import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../config/app_config.dart';

class IntakeFormScreen extends StatefulWidget {
  final Map<String, dynamic> profile;

  const IntakeFormScreen({super.key, required this.profile});

  @override
  State<IntakeFormScreen> createState() => _IntakeFormScreenState();
}

class _IntakeFormScreenState extends State<IntakeFormScreen> {
  static const _section1Fields = <String, String>{
    'q1_preferred_name': 'Preferred name',
    'q2_pronouns': 'Pronouns',
    'q3_household_relationship': 'Household and relationship',
    'q4_bringing_you_in': 'What is bringing you in right now?',
    'q5_how_long': 'How long has this been going on?',
    'q6_hope_to_get': 'What do you hope to get from this?',
    'q7_successful_outcome': 'What would success look like?',
    'q8_biggest_things_weighing': 'Biggest things weighing on you',
    'q9_support_network': 'Support network',
    'q10_current_wellbeing': 'Current wellbeing',
    'q11_communication_preferences': 'Communication preferences',
    'q12_anything_else_upfront': 'Anything else upfront',
  };

  static const _section2Fields = <String, String>{
    'q13_emergency_contact_name': 'Emergency contact name',
    'q13_emergency_contact_phone': 'Emergency contact phone',
    'q14_address': 'Address',
    'q15_prior_treatment': 'Prior treatment',
    'q16_current_medications': 'Current medications',
    'q17_family_history': 'Family history',
    'q18_suicide_self_harm_history': 'Suicide/self-harm history',
    'q19_trauma_history': 'Trauma history',
    'q20_substance_use': 'Substance use',
    'q21_sleep_appetite_energy': 'Sleep/appetite/energy',
  };

  static const _enumChoices = <String, List<String>>{
    'q9_support_network': ['yes', 'somewhat', 'no'],
    'q10_current_wellbeing': ['not_satisfactory', 'satisfactory', 'thriving'],
  };

  Map<String, dynamic>? _intake;
  bool _loading = true;
  bool _saving = false;
  String _error = '';

  String get _token => (widget.profile['token'] ?? '').toString();

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = '';
    });
    try {
      final resp = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/client/intake'),
        headers: {'Authorization': 'Bearer $_token'},
      );
      if (resp.statusCode != 200) {
        setState(() {
          _error = 'Failed to load intake (${resp.statusCode})';
          _loading = false;
        });
        return;
      }
      setState(() {
        _intake = jsonDecode(resp.body) as Map<String, dynamic>;
        _loading = false;
      });
    } catch (e) {
      setState(() {
        _error = 'Failed to load intake: $e';
        _loading = false;
      });
    }
  }

  Future<void> _saveField(String key, dynamic value) async {
    setState(() => _saving = true);
    try {
      final resp = await http.patch(
        Uri.parse('${AppConfig.apiBaseUrl}/api/client/intake/$key'),
        headers: {
          'Authorization': 'Bearer $_token',
          'Content-Type': 'application/json',
        },
        body: jsonEncode({'value': value}),
      );
      if (resp.statusCode != 200) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Save failed (${resp.statusCode})')),
        );
        return;
      }
      if (!mounted) return;
      setState(() => _intake = jsonDecode(resp.body) as Map<String, dynamic>);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _editField(String key, String label) async {
    final existing = (_intake?[key] ?? '').toString();
    if (_enumChoices.containsKey(key)) {
      String selected = existing.isEmpty ? _enumChoices[key]!.first : existing;
      final result = await showDialog<String>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text(label),
          content: StatefulBuilder(
            builder: (ctx, setLocal) => Column(
              mainAxisSize: MainAxisSize.min,
              children: _enumChoices[key]!
                  .map((v) => RadioListTile<String>(
                        title: Text(v),
                        value: v,
                        groupValue: selected,
                        onChanged: (next) {
                          if (next == null) return;
                          setLocal(() => selected = next);
                        },
                      ))
                  .toList(),
            ),
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('Cancel')),
            ElevatedButton(
                onPressed: () => Navigator.pop(ctx, selected),
                child: const Text('Save')),
          ],
        ),
      );
      if (result != null) await _saveField(key, result);
      return;
    }

    final controller = TextEditingController(text: existing);
    final result = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(label),
        content: TextField(
          controller: controller,
          minLines: 1,
          maxLines: 5,
          autofocus: true,
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
          ElevatedButton(
              onPressed: () => Navigator.pop(ctx, controller.text.trim()),
              child: const Text('Save')),
        ],
      ),
    );
    if (result != null) await _saveField(key, result);
  }

  Widget _sectionCard({
    required String title,
    required String subtitle,
    required Color chipColor,
    required Map<String, String> fields,
  }) {
    return Card(
      color: const Color(0xFF111111),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  decoration: BoxDecoration(
                      color: chipColor.withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(10)),
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  child: Text(title,
                      style: TextStyle(
                          color: chipColor, fontWeight: FontWeight.w600)),
                ),
                const SizedBox(width: 8),
                Expanded(
                    child: Text(subtitle,
                        style: const TextStyle(
                            color: Colors.white70, fontSize: 12))),
              ],
            ),
            const SizedBox(height: 8),
            for (final entry in fields.entries)
              ListTile(
                contentPadding: EdgeInsets.zero,
                title: Text(entry.value,
                    style: const TextStyle(color: Colors.white)),
                subtitle: Text(
                  ((_intake?[entry.key] ?? '').toString().trim().isEmpty)
                      ? 'Not yet answered'
                      : (_intake?[entry.key] ?? '').toString(),
                  style: const TextStyle(color: Colors.white60),
                ),
                trailing: TextButton(
                  onPressed:
                      _saving ? null : () => _editField(entry.key, entry.value),
                  child: const Text('Edit'),
                ),
              ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF050505),
      appBar: AppBar(
        title: const Text('Clinical Intake'),
        backgroundColor: const Color(0xFF050505),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error.isNotEmpty
              ? Center(
                  child: Text(_error,
                      style: const TextStyle(color: Colors.redAccent)))
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView(
                    padding: const EdgeInsets.all(12),
                    children: [
                      const Text(
                        'This intake helps Little Nate build rapport and helps your coach prepare clinically.',
                        style: TextStyle(color: Colors.white70),
                      ),
                      const SizedBox(height: 8),
                      Card(
                        color: const Color(0xFF0A0A0A),
                        child: ListTile(
                          title: const Text(
                              'Walk through it with Little Nate (+1000 per question)',
                              style: TextStyle(color: Colors.white)),
                          subtitle: const Text(
                              'Open chat and say: "Let\'s do intake now"',
                              style: TextStyle(color: Colors.white60)),
                          trailing: const Icon(Icons.chat_bubble_outline,
                              color: Color(0xFF4ECDC4)),
                          onTap: () {
                            ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(
                                  content: Text(
                                      'Open chat and say: "Let\'s do intake now"')),
                            );
                          },
                        ),
                      ),
                      const SizedBox(height: 8),
                      _sectionCard(
                        title: 'Shared with Little Nate and your coach',
                        subtitle: 'Section 1',
                        chipColor: const Color(0xFF4ECDC4),
                        fields: _section1Fields,
                      ),
                      _sectionCard(
                        title: 'Shared with your coach only',
                        subtitle: 'Section 2 (Little Nate cannot access)',
                        chipColor: const Color(0xFF9D4EDD),
                        fields: _section2Fields,
                      ),
                    ],
                  ),
                ),
    );
  }
}
