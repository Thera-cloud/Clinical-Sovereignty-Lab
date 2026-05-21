import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../config/app_config.dart';

class IntakeFormCoachPanel extends StatefulWidget {
  final String clientUsername;
  final String token;
  final String clientDisplayName;

  const IntakeFormCoachPanel({
    super.key,
    required this.clientUsername,
    required this.token,
    required this.clientDisplayName,
  });

  @override
  State<IntakeFormCoachPanel> createState() => _IntakeFormCoachPanelState();
}

class _IntakeFormCoachPanelState extends State<IntakeFormCoachPanel> {
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

  Map<String, dynamic>? _data;
  bool _loading = true;
  bool _saving = false;
  String _error = '';

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
        Uri.parse(
            '${AppConfig.apiBaseUrl}/api/coach/intake/${widget.clientUsername}'),
        headers: {'Authorization': 'Bearer ${widget.token}'},
      );
      if (resp.statusCode != 200) {
        setState(() {
          _error = 'Failed to load intake (${resp.statusCode})';
          _loading = false;
        });
        return;
      }
      setState(() {
        _data = jsonDecode(resp.body) as Map<String, dynamic>;
        _loading = false;
      });
    } catch (e) {
      setState(() {
        _error = 'Failed to load intake: $e';
        _loading = false;
      });
    }
  }

  Future<void> _patchSection2Field(String key, String value) async {
    setState(() => _saving = true);
    try {
      final resp = await http.patch(
        Uri.parse(
            '${AppConfig.apiBaseUrl}/api/coach/intake/${widget.clientUsername}/$key'),
        headers: {
          'Authorization': 'Bearer ${widget.token}',
          'Content-Type': 'application/json',
        },
        body: jsonEncode({'value': value}),
      );
      if (resp.statusCode != 200) return;
      setState(() => _data = jsonDecode(resp.body) as Map<String, dynamic>);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _editSection2(String key, String label) async {
    final controller =
        TextEditingController(text: (_data?[key] ?? '').toString());
    final value = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(label),
        content: TextField(controller: controller, minLines: 1, maxLines: 5),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
          ElevatedButton(
              onPressed: () => Navigator.pop(ctx, controller.text.trim()),
              child: const Text('Save')),
        ],
      ),
    );
    if (value != null) await _patchSection2Field(key, value);
  }

  Future<void> _saveStyleGuidance() async {
    final controller = TextEditingController(
        text: (_data?['coach_nate_style_guidance'] ?? '').toString());
    final value = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Coach Rapport Guidance'),
        content: TextField(
          controller: controller,
          minLines: 2,
          maxLines: 6,
          decoration: const InputDecoration(
            hintText:
                'Style-only guidance (pace, language, scaffolding). No diagnosis terms.',
          ),
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
    if (value == null) return;
    setState(() => _saving = true);
    try {
      final resp = await http.patch(
        Uri.parse(
            '${AppConfig.apiBaseUrl}/api/coach/intake/${widget.clientUsername}/nate-style-guidance'),
        headers: {
          'Authorization': 'Bearer ${widget.token}',
          'Content-Type': 'application/json',
        },
        body: jsonEncode({'value': value}),
      );
      if (resp.statusCode == 200) {
        setState(() => _data = jsonDecode(resp.body) as Map<String, dynamic>);
      } else if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
              content: Text('Could not save guidance (${resp.statusCode})')),
        );
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _sendReminder() async {
    final noteController = TextEditingController();
    bool section1 = true;
    bool section2 = true;
    bool email = false;
    bool sms = false;
    bool override = false;
    final overrideController = TextEditingController();
    final approved = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          title: const Text('Send intake reminder'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                CheckboxListTile(
                  value: section1,
                  onChanged: (v) => setLocal(() => section1 = v ?? true),
                  title: const Text('Section 1'),
                ),
                CheckboxListTile(
                  value: section2,
                  onChanged: (v) => setLocal(() => section2 = v ?? true),
                  title: const Text('Section 2'),
                ),
                CheckboxListTile(
                  value: email,
                  onChanged: (v) => setLocal(() => email = v ?? false),
                  title: const Text('Email'),
                ),
                CheckboxListTile(
                  value: sms,
                  onChanged: (v) => setLocal(() => sms = v ?? false),
                  title: const Text('SMS'),
                ),
                CheckboxListTile(
                  value: override,
                  onChanged: (v) => setLocal(() => override = v ?? false),
                  title: const Text('Override 7-day limit'),
                ),
                if (override)
                  TextField(
                    controller: overrideController,
                    minLines: 2,
                    maxLines: 4,
                    decoration: const InputDecoration(
                        labelText: 'Override reason (required, min 10 chars)'),
                  ),
                TextField(
                  controller: noteController,
                  minLines: 2,
                  maxLines: 4,
                  decoration:
                      const InputDecoration(labelText: 'Optional coach note'),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(ctx, false),
                child: const Text('Cancel')),
            ElevatedButton(
                onPressed: () => Navigator.pop(ctx, true),
                child: const Text('Send')),
          ],
        ),
      ),
    );
    if (approved != true) return;

    final sections = <String>[
      if (section1) 'section_1',
      if (section2) 'section_2',
    ];
    final methods = <String>[
      'in_app',
      if (email) 'email',
      if (sms) 'sms',
    ];
    setState(() => _saving = true);
    try {
      final resp = await http.post(
        Uri.parse(
            '${AppConfig.apiBaseUrl}/api/coach/intake/${widget.clientUsername}/remind'),
        headers: {
          'Authorization': 'Bearer ${widget.token}',
          'Content-Type': 'application/json',
        },
        body: jsonEncode({
          'sections': sections,
          'methods': methods,
          'personal_note': noteController.text.trim(),
          'override_rate_limit': override,
          'override_reason': overrideController.text.trim(),
        }),
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
            content: Text(resp.statusCode == 200
                ? 'Reminder sent'
                : 'Reminder failed (${resp.statusCode})')),
      );
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _markSection2Complete() async {
    setState(() => _saving = true);
    try {
      final resp = await http.post(
        Uri.parse(
            '${AppConfig.apiBaseUrl}/api/coach/intake/${widget.clientUsername}/complete-section-2'),
        headers: {'Authorization': 'Bearer ${widget.token}'},
      );
      if (resp.statusCode == 200)
        setState(() => _data = jsonDecode(resp.body) as Map<String, dynamic>);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF050505),
      appBar: AppBar(
        title: Text('Intake • ${widget.clientDisplayName}'),
        backgroundColor: const Color(0xFF050505),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error.isNotEmpty
              ? Center(
                  child: Text(_error,
                      style: const TextStyle(color: Colors.redAccent)))
              : ListView(
                  padding: const EdgeInsets.all(12),
                  children: [
                    Card(
                      color: const Color(0xFF111111),
                      child: ListTile(
                        title: const Text(
                            'Coach rapport guidance for Little Nate',
                            style: TextStyle(color: Colors.white)),
                        subtitle: Text(
                          (_data?['coach_nate_style_guidance'] ?? '')
                                  .toString()
                                  .isEmpty
                              ? 'No guidance set'
                              : (_data?['coach_nate_style_guidance'] ?? '')
                                  .toString(),
                          style: const TextStyle(color: Colors.white70),
                        ),
                        trailing: TextButton(
                            onPressed: _saving ? null : _saveStyleGuidance,
                            child: const Text('Edit')),
                      ),
                    ),
                    const SizedBox(height: 8),
                    const Text('Section 1 (read-only)',
                        style: TextStyle(
                            color: Color(0xFF4ECDC4),
                            fontWeight: FontWeight.bold)),
                    const SizedBox(height: 6),
                    for (final entry in _section1Fields.entries)
                      ListTile(
                        title: Text(entry.value,
                            style: const TextStyle(color: Colors.white)),
                        subtitle: Text(
                          ((_data?[entry.key] ?? '').toString().trim().isEmpty)
                              ? 'Not yet completed'
                              : (_data?[entry.key] ?? '').toString(),
                          style: const TextStyle(color: Colors.white60),
                        ),
                      ),
                    const Divider(color: Colors.white12),
                    const Text('Section 2 (coach-editable)',
                        style: TextStyle(
                            color: Color(0xFF9D4EDD),
                            fontWeight: FontWeight.bold)),
                    const SizedBox(height: 6),
                    for (final entry in _section2Fields.entries)
                      ListTile(
                        title: Text(entry.value,
                            style: const TextStyle(color: Colors.white)),
                        subtitle: Text(
                          ((_data?[entry.key] ?? '').toString().trim().isEmpty)
                              ? 'Not yet completed'
                              : (_data?[entry.key] ?? '').toString(),
                          style: const TextStyle(color: Colors.white60),
                        ),
                        trailing: TextButton(
                          onPressed: _saving
                              ? null
                              : () => _editSection2(entry.key, entry.value),
                          child: const Text('Edit'),
                        ),
                      ),
                    const SizedBox(height: 12),
                    Wrap(
                      spacing: 10,
                      runSpacing: 10,
                      children: [
                        ElevatedButton(
                          onPressed: _saving ? null : _markSection2Complete,
                          child: const Text('Mark Section 2 Complete'),
                        ),
                        OutlinedButton(
                          onPressed: _saving ? null : _sendReminder,
                          child: const Text('Send Reminder to Client'),
                        ),
                      ],
                    ),
                  ],
                ),
    );
  }
}
