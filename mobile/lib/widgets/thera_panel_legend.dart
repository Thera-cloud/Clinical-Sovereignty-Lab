import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

/// Shared C3 legend sheet for Vault and Thera-World.
void showTheraPanelLegend({
  required BuildContext context,
  required String apiBase,
  required String panelId,
  required Map<String, String> authHeaders,
  VoidCallback? onGoDeeper,
}) {
  if (panelId.trim().isEmpty || panelId == 'archetype') return;
  final origin = apiBase.replaceAll(RegExp(r'/api/?$'), '').replaceAll(RegExp(r'/+$'), '');
  showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    backgroundColor: const Color(0xFF0A0A0A),
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
    ),
    builder: (ctx) => FutureBuilder<Map<String, dynamic>?>(
      future: _fetchCodex(origin, panelId, authHeaders),
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const SizedBox(
            height: 160,
            child: Center(
              child: CircularProgressIndicator(color: Color(0xFF9D4EDD)),
            ),
          );
        }
        final data = snapshot.data;
        final legend = (data?['legend'] as List?) ?? [];
        final thread = (data?['journey_thread'] ?? '').toString();
        final seq = data?['panel_sequence'];
        final biomeLabel = (data?['biome_label'] ?? '').toString();
        final isNeuro = (data?['region'] ?? '').toString() == 'neuro';
        // APHL — Little Nate's wondering figures (tier "inferred") + opt-in switch.
        final hypEnabled = data?['hypothesis_enabled'] == true;
        var hypOptIn = data?['hypothesis_opt_in'] == true;
        final engagedKinds = <String, String>{};
        var optInBusy = false;
        return StatefulBuilder(builder: (context, setSheetState) {
        return DraggableScrollableSheet(
          initialChildSize: 0.62,
          minChildSize: 0.35,
          maxChildSize: 0.95,
          expand: false,
          builder: (_, scrollCtrl) => ListView(
            controller: scrollCtrl,
            padding: const EdgeInsets.all(20),
            children: [
              Text(
                seq != null ? 'Legend — panel $seq' : 'Legend',
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                ),
              ),
              if (isNeuro && biomeLabel.isNotEmpty) ...[
                const SizedBox(height: 4),
                Text(
                  biomeLabel,
                  style: const TextStyle(
                    color: Color(0xFF4ECDC4),
                    fontSize: 12,
                    letterSpacing: 0.6,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
              const SizedBox(height: 4),
              Text(
                isNeuro
                    ? 'Why these figures are in this still, and the step this scene is holding.'
                    : 'What each figure is doing in this still.',
                style: const TextStyle(color: Color(0xFF888888), fontSize: 13, height: 1.4),
              ),
              if (thread.isNotEmpty) ...[
                const SizedBox(height: 14),
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: const Color(0xFF9D4EDD).withValues(alpha: 0.08),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(
                      color: const Color(0xFF9D4EDD).withValues(alpha: 0.25),
                    ),
                  ),
                  child: Text(
                    thread,
                    style: const TextStyle(
                      color: Color(0xFFE8D5A3),
                      fontSize: 13,
                      height: 1.45,
                    ),
                  ),
                ),
              ],
              const SizedBox(height: 16),
              if (legend.isEmpty)
                const Text(
                  'The landscape itself is the figure here. Go deeper with Nate to sit with the scene.',
                  style: TextStyle(color: Color(0xFF888888)),
                ),
              ...legend.map((e) {
                final row = e is Map ? e : <String, dynamic>{};
                if (row['tier']?.toString() == 'inferred') {
                  final hypId = row['symbol_id']
                          ?.toString()
                          .replaceFirst('hypothesis:', '') ??
                      '';
                  return _HypothesisLegendCard(
                    row: row,
                    decided: engagedKinds[hypId],
                    onAct: (kind) async {
                      final res = await _engageHypothesis(
                          origin, hypId, kind, authHeaders);
                      if (res == null) {
                        if (context.mounted) {
                          ScaffoldMessenger.maybeOf(context)?.showSnackBar(
                            const SnackBar(
                                content: Text(
                                    'Could not reach Nate just now — try again shortly.')),
                          );
                        }
                        return;
                      }
                      setSheetState(() => engagedKinds[hypId] = kind);
                      final line = (res['nate_line'] ?? '').toString();
                      if (line.isNotEmpty && context.mounted) {
                        ScaffoldMessenger.maybeOf(context)?.showSnackBar(
                          SnackBar(
                            content: Text(line),
                            backgroundColor: const Color(0xFF1A1A1A),
                            duration: const Duration(seconds: 5),
                          ),
                        );
                      }
                    },
                  );
                }
                final name = row['display_name']?.toString() ?? '';
                final inPanel = row['figure_in_panel']?.toString() ?? '';
                final role = row['role']?.toString() ?? '';
                final prior = row['prior_note']?.toString() ?? '';
                final meaning = row['meaning']?.toString() ?? '';
                final isCore = row['is_core'] == true;
                final purpose = row['purpose']?.toString() ?? '';
                final mirror = row['archetype_mirror']?.toString() ?? '';
                // Neuro figures: `meaning` duplicates `purpose` — show it once, under its own header.
                final showMeaning = meaning.isNotEmpty && meaning != purpose;
                return Padding(
                  padding: const EdgeInsets.only(bottom: 18),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(children: [
                        Expanded(
                          child: Text(
                            name,
                            style: const TextStyle(
                              color: Color(0xFF9D4EDD),
                              fontWeight: FontWeight.bold,
                              fontSize: 15,
                            ),
                          ),
                        ),
                        if (isCore)
                          const Text(
                            'core',
                            style: TextStyle(
                              color: Color(0xFFC9A962),
                              fontSize: 11,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                      ]),
                      if (role.isNotEmpty) ...[
                        const SizedBox(height: 4),
                        Text(
                          role,
                          style: const TextStyle(
                            color: Color(0xFF4ECDC4),
                            fontSize: 12,
                            fontStyle: FontStyle.italic,
                          ),
                        ),
                      ],
                      if (inPanel.isNotEmpty) ...[
                        const SizedBox(height: 6),
                        Text(
                          inPanel,
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 13,
                            height: 1.45,
                          ),
                        ),
                      ],
                      if (prior.isNotEmpty) ...[
                        const SizedBox(height: 6),
                        Text(
                          prior,
                          style: const TextStyle(
                            color: Color(0xFFE8D5A3),
                            fontSize: 12,
                            height: 1.4,
                          ),
                        ),
                      ],
                      if (purpose.isNotEmpty) ...[
                        const SizedBox(height: 8),
                        _legendSubhead('Purpose'),
                        const SizedBox(height: 3),
                        Text(
                          purpose,
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 13,
                            height: 1.45,
                          ),
                        ),
                      ],
                      if (mirror.isNotEmpty) ...[
                        const SizedBox(height: 8),
                        _legendSubhead('How they meet you'),
                        const SizedBox(height: 3),
                        Text(
                          mirror,
                          style: const TextStyle(
                            color: Color(0xFFE8D5A3),
                            fontSize: 13,
                            height: 1.45,
                          ),
                        ),
                      ],
                      if (showMeaning) ...[
                        const SizedBox(height: 6),
                        Text(
                          meaning,
                          style: const TextStyle(
                            color: Colors.white70,
                            fontSize: 12,
                            height: 1.4,
                          ),
                        ),
                      ],
                    ],
                  ),
                );
              }),
              if (hypEnabled) ...[
                const SizedBox(height: 6),
                Container(
                  decoration: BoxDecoration(
                    color: const Color(0xFF4ECDC4).withValues(alpha: 0.06),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(
                      color: const Color(0xFF4ECDC4).withValues(alpha: 0.22),
                    ),
                  ),
                  child: SwitchListTile(
                    dense: true,
                    contentPadding:
                        const EdgeInsets.symmetric(horizontal: 12, vertical: 2),
                    activeColor: const Color(0xFF4ECDC4),
                    value: hypOptIn,
                    title: Text(
                      hypOptIn
                          ? 'Show the figures Nate wonders about'
                          : 'Nate is wondering quietly',
                      style: const TextStyle(color: Colors.white, fontSize: 13),
                    ),
                    subtitle: Text(
                      hypOptIn
                          ? 'Every few panels Nate may add one figure he is curious about. '
                              'You can always say "that\'s not me", or switch this off.'
                          : 'Nothing new appears in your panels while this is off. '
                              'Switch it back on whenever you want to see what Nate is wondering.',
                      style: const TextStyle(color: Color(0xFF888888), fontSize: 11, height: 1.35),
                    ),
                    onChanged: optInBusy
                        ? null
                        : (v) async {
                            setSheetState(() => optInBusy = true);
                            final ok =
                                await _setHypothesisOptIn(origin, v, authHeaders);
                            setSheetState(() {
                              optInBusy = false;
                              if (ok) hypOptIn = v;
                            });
                            if (!ok && context.mounted) {
                              ScaffoldMessenger.maybeOf(context)?.showSnackBar(
                                const SnackBar(
                                    content: Text(
                                        'Begin your Thera-World journey first, then Nate can wonder with you.')),
                              );
                            }
                          },
                  ),
                ),
              ],
              if (onGoDeeper != null) ...[
                const SizedBox(height: 8),
                ElevatedButton.icon(
                  icon: const Icon(Icons.forum_outlined, size: 18),
                  label: const Text('Go deeper with Nate'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFFC9A962),
                    foregroundColor: Colors.black,
                  ),
                  onPressed: () {
                    Navigator.pop(ctx);
                    onGoDeeper();
                  },
                ),
              ],
            ],
          ),
        );
        });
      },
    ),
  );
}

/// APHL — one figure Little Nate is wondering about. Tentative framing, three
/// client verbs. `decided` locks the card after the client answers.
class _HypothesisLegendCard extends StatelessWidget {
  const _HypothesisLegendCard({
    required this.row,
    required this.onAct,
    this.decided,
  });

  final Map row;
  final String? decided;
  final Future<void> Function(String kind) onAct;

  @override
  Widget build(BuildContext context) {
    final name = row['display_name']?.toString() ?? 'a figure';
    final question = row['meaning']?.toString() ?? '';
    final inPanel = row['figure_in_panel']?.toString() ?? '';
    final status = (decided ?? row['status']?.toString() ?? 'proposed');
    const cyan = Color(0xFF4ECDC4);
    String? decidedLabel;
    switch (status) {
      case 'confirmed':
        decidedLabel = 'You said this fits — your coach can see it now.';
        break;
      case 'banished':
        decidedLabel = 'You said this is not you — Nate has set it down.';
        break;
      case 'engaged':
        decidedLabel = 'Nate will keep wondering with you.';
        break;
      case 'held':
        decidedLabel = 'Your coach is holding this one for now.';
        break;
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: 18),
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: cyan.withValues(alpha: 0.06),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: cyan.withValues(alpha: 0.3)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              const Icon(Icons.auto_awesome, size: 14, color: cyan),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  name,
                  style: const TextStyle(
                    color: cyan,
                    fontWeight: FontWeight.bold,
                    fontSize: 15,
                  ),
                ),
              ),
              const Text(
                'nate is wondering',
                style: TextStyle(
                  color: Color(0xFF8B7355),
                  fontSize: 10,
                  letterSpacing: 1.0,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ]),
            if (inPanel.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(
                inPanel,
                style: const TextStyle(color: Colors.white, fontSize: 13, height: 1.45),
              ),
            ],
            if (question.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                question,
                style: const TextStyle(
                  color: Color(0xFFE8D5A3),
                  fontSize: 13,
                  fontStyle: FontStyle.italic,
                  height: 1.45,
                ),
              ),
            ],
            const SizedBox(height: 10),
            if (decidedLabel != null)
              Text(
                decidedLabel,
                style: const TextStyle(color: Color(0xFF888888), fontSize: 12),
              )
            else
              Wrap(
                spacing: 8,
                runSpacing: 6,
                children: [
                  _hypButton('That fits', Icons.check, const Color(0xFFC9A962),
                      () => onAct('confirm')),
                  _hypButton('Tell me more', Icons.chat_bubble_outline, cyan,
                      () => onAct('curious')),
                  _hypButton('That\'s not me', Icons.close, const Color(0xFF888888),
                      () => onAct('banish')),
                ],
              ),
          ],
        ),
      ),
    );
  }

  Widget _hypButton(
      String label, IconData icon, Color color, VoidCallback onPressed) {
    return OutlinedButton.icon(
      onPressed: onPressed,
      icon: Icon(icon, size: 14, color: color),
      label: Text(label, style: TextStyle(color: color, fontSize: 12)),
      style: OutlinedButton.styleFrom(
        side: BorderSide(color: color.withValues(alpha: 0.5)),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        minimumSize: Size.zero,
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
      ),
    );
  }
}

Future<Map<String, dynamic>?> _engageHypothesis(
  String origin,
  String hypothesisId,
  String kind,
  Map<String, String> authHeaders,
) async {
  if (hypothesisId.isEmpty) return null;
  try {
    final resp = await http
        .post(
          Uri.parse('$origin/api/sse-client/hypothesis/engage'),
          headers: {...authHeaders, 'Content-Type': 'application/json'},
          body: jsonEncode({'hypothesis_id': hypothesisId, 'kind': kind}),
        )
        .timeout(const Duration(seconds: 10));
    if (resp.statusCode >= 200 && resp.statusCode < 300) {
      return jsonDecode(resp.body) as Map<String, dynamic>;
    }
  } catch (_) {}
  return null;
}

Future<bool> _setHypothesisOptIn(
  String origin,
  bool value,
  Map<String, String> authHeaders,
) async {
  try {
    final resp = await http
        .post(
          Uri.parse('$origin/api/sse-client/hypothesis/opt-in'),
          headers: {...authHeaders, 'Content-Type': 'application/json'},
          body: jsonEncode({'opt_in': value}),
        )
        .timeout(const Duration(seconds: 10));
    return resp.statusCode >= 200 && resp.statusCode < 300;
  } catch (_) {
    return false;
  }
}

Widget _legendSubhead(String label) => Text(
      label.toUpperCase(),
      style: const TextStyle(
        color: Color(0xFF8B7355),
        fontSize: 10,
        letterSpacing: 1.1,
        fontWeight: FontWeight.w700,
      ),
    );

Future<Map<String, dynamic>?> _fetchCodex(
  String origin,
  String panelId,
  Map<String, String> authHeaders,
) async {
  try {
    final resp = await http
        .get(
          Uri.parse('$origin/api/sse-client/codex/panel/$panelId'),
          headers: authHeaders,
        )
        .timeout(const Duration(seconds: 8));
    if (resp.statusCode >= 200 && resp.statusCode < 300) {
      return jsonDecode(resp.body) as Map<String, dynamic>;
    }
  } catch (_) {}
  return null;
}
