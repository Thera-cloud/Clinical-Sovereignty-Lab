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
                    ? 'Who stands in this scene, why they are here, and how they meet you where you are.'
                    : 'How to read the figures in this panel, and how this scene continues Little Nate\'s understanding of you over time.',
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
      },
    ),
  );
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
