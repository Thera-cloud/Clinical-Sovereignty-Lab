// =============================================================================
// SENSITIVE CLINICAL PROFILE — INSPECTION HARNESS (DEBUG-ONLY)
//
// Local Flutter dev preview for `sensitive_clinical_profile_screen.dart`.
// Renders three buttons that push the production screen against the in-memory
// fixtures defined in `sensitive_profile_inspection_fixture.dart`, bypassing
// the real `_loadProfile()` / `_loadActivityLog()` REST calls.
//
// Reachability: this screen is ONLY pushable through the `kDebugMode`-gated
// URL handler in `mobile/lib/main.dart` (`?dev=sensitive-profile-inspection`
// or `#/dev/sensitive-profile-inspection`). Release builds short-circuit that
// gate to `false`, so this file's `Navigator.push` calls are unreachable
// outside `flutter run --debug`.
//
// Coach view note: the user testing this harness is logging in as `CoachN`
// in the real product. The harness mirrors that — the COACH buttons set
// `currentUserProfile.role = 'COACH'` and `username = 'CoachN'` so the screen
// renders the clinician panels (codeword propose, threshold sliders), and the
// ADMIN button flips just the role flag so admin-only UI elements (Safe
// Silence approve form) become visible against the same dataset.
// =============================================================================

import 'package:flutter/foundation.dart' show kDebugMode;
import 'package:flutter/material.dart';

import '../sensitive_clinical_profile_screen.dart';
import 'sensitive_profile_inspection_fixture.dart';

class SensitiveProfileInspectionHarness extends StatelessWidget {
  const SensitiveProfileInspectionHarness({super.key});

  // Design tokens — mirror the surrounding sensitive-clinical-profile screen
  // so the harness chrome doesn't look out of place when sandwiched between
  // hot reloads of the real screen.
  static const _bgVoid = Color(0xFF050505);
  static const _bgCard = Color(0xFF111111);
  static const _bgElev = Color(0xFF1A1A1A);
  static const _gold = Color(0xFFC9A962);
  static const _goldDim = Color(0xFF8B7355);
  static const _cyan = Color(0xFF4ECDC4);
  static const _purple = Color(0xFF9D4EDD);
  static const _text = Color(0xFFFFFFFF);
  static const _textDim = Color(0xFF888888);
  static const _border = Color(0xFF252525);

  @override
  Widget build(BuildContext context) {
    // Defense-in-depth: even if a release build somehow routes here, refuse
    // to render anything operational. The URL gate in main.dart already
    // blocks this path, but a dev convenience screen MUST never be a release
    // surface.
    if (!kDebugMode) {
      return Scaffold(
        backgroundColor: _bgVoid,
        body: Center(
          child: Text(
            'Inspection harness is debug-only.',
            style: TextStyle(color: _gold.withValues(alpha: 0.7)),
          ),
        ),
      );
    }

    return Scaffold(
      backgroundColor: _bgVoid,
      appBar: AppBar(
        backgroundColor: _bgCard,
        elevation: 0,
        title: const Text(
          'Sensitive Profile · Inspection Harness',
          style: TextStyle(color: _gold, fontSize: 16),
        ),
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: ListView(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 24),
            shrinkWrap: true,
            children: [
              _banner(),
              const SizedBox(height: 16),
              _button(
                context,
                label: 'View enrolled state (coach role)',
                helper:
                    'Pushes SensitiveClinicalProfileScreen with the enrolled '
                    'fixture and role=COACH (CoachN). Renders all 9 sections '
                    'populated; interactive controls visible; Safe Silence shows '
                    'pending + Cancel Proposal when proposer matches.',
                color: _gold,
                icon: Icons.shield_outlined,
                onPressed: () => _pushEnrolled(context, role: 'COACH'),
              ),
              const SizedBox(height: 12),
              _button(
                context,
                label: 'View not-enrolled state',
                helper:
                    'Pushes SensitiveClinicalProfileScreen with '
                    'loadErrorOverride set, so the screen renders its '
                    'standard error UI as if the API returned 404 not_enrolled.',
                color: _cyan,
                icon: Icons.report_gmailerrorred_outlined,
                onPressed: () => _pushNotEnrolled(context),
              ),
              const SizedBox(height: 12),
              _button(
                context,
                label: 'View enrolled state (admin role)',
                helper:
                    'Same enrolled dataset, role=ADMIN. Safe Silence: approve '
                    '+ reject proposal. Activity log row 6006 exercises '
                    'admin-redacted subtitle.',
                color: _purple,
                icon: Icons.admin_panel_settings_outlined,
                onPressed: () => _pushEnrolled(context, role: 'ADMIN'),
              ),
              const SizedBox(height: 24),
              _legend(),
            ],
          ),
        ),
      ),
    );
  }

  // ---------------------------------------------------------------------------
  // Push handlers — each constructs the production screen with override
  // params populated. The screen's `_loadProfile()` and `_loadActivityLog()`
  // detect those params and short-circuit, so no real network call fires.
  // ---------------------------------------------------------------------------

  void _pushEnrolled(BuildContext context, {required String role}) {
    final fix = SensitiveProfileInspectionFixture.enrolledFixture;
    Navigator.of(context).push(
      MaterialPageRoute(
        settings: RouteSettings(
          name: '/dev/sensitive-profile-inspection/enrolled-${role.toLowerCase()}',
        ),
        builder: (_) => SensitiveClinicalProfileScreen(
          // Mocked auth profile — token is intentionally a sentinel that
          // would be rejected by any real API; the override branches in the
          // screen ensure no network call is made.
          currentUserProfile: {
            'username': role == 'ADMIN' ? 'DrNevedal1' : 'CoachN',
            'role': role,
            'token': 'inspection-harness-no-network',
          },
          targetUserId: fix.profile.userId,
          profileOverride: fix.profile,
          logEventsOverride: fix.logEvents,
        ),
      ),
    );
  }

  void _pushNotEnrolled(BuildContext context) {
    final fix = SensitiveProfileInspectionFixture.notEnrolledFixture;
    Navigator.of(context).push(
      MaterialPageRoute(
        settings: const RouteSettings(
          name: '/dev/sensitive-profile-inspection/not-enrolled',
        ),
        builder: (_) => SensitiveClinicalProfileScreen(
          currentUserProfile: const {
            'username': 'CoachN',
            'role': 'COACH',
            'token': 'inspection-harness-no-network',
          },
          targetUserId: fix.profile.userId,
          // Drive the screen straight into its error UI; profileOverride is
          // intentionally null so the loadErrorOverride branch wins.
          loadErrorOverride: fix.notEnrolledError,
        ),
      ),
    );
  }

  // ---------------------------------------------------------------------------
  // Chrome
  // ---------------------------------------------------------------------------

  Widget _banner() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: _bgCard,
        border: Border.all(color: _gold.withValues(alpha: 0.5)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: const Row(
        children: [
          Icon(Icons.science_outlined, color: _gold, size: 20),
          SizedBox(width: 10),
          Expanded(
            child: Text(
              'Local dev preview — no network calls. Fixtures live in '
              'sensitive_profile_inspection_fixture.dart and only this '
              'screen consumes them.',
              style: TextStyle(color: _text, fontSize: 12, height: 1.35),
            ),
          ),
        ],
      ),
    );
  }

  Widget _legend() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: _bgElev,
        border: Border.all(color: _border),
        borderRadius: BorderRadius.circular(6),
      ),
      child: const Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'What to verify in the enrolled view:',
            style: TextStyle(
              color: _gold,
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
          SizedBox(height: 6),
          Text(
            '• Embodiment badge: cyan "transitioning"\n'
            '• Thresholds badge: purple "overridden" (1.50 vs 0.60 preset)\n'
            '• Codewords badge: gold "2 active"\n'
            '• Trigger Dates badge: red "within 7d" (date 3 days out)\n'
            '• Polyvictim badge: red "2 · high"\n'
            '• Legal badge: cyan "event in 8d"\n'
            '• Safe Silence badge: yellow "pending_approval"\n'
            '• Activity Log badge: cyan "10 rows · 7d"\n'
            '\n'
            'In ADMIN view, Safe Silence panel renders the approve form '
            'instead of propose; row 6006 (admin_audit_review) renders the '
            'redacted-subtitle path.',
            style: TextStyle(color: _textDim, fontSize: 11, height: 1.45),
          ),
        ],
      ),
    );
  }

  Widget _button(
    BuildContext context, {
    required String label,
    required String helper,
    required Color color,
    required IconData icon,
    required VoidCallback onPressed,
  }) {
    return Container(
      decoration: BoxDecoration(
        color: _bgCard,
        border: Border.all(color: color.withValues(alpha: 0.5)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(8),
          onTap: onPressed,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(icon, color: color, size: 22),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        label,
                        style: TextStyle(
                          color: color,
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        helper,
                        style: const TextStyle(
                          color: _textDim,
                          fontSize: 11,
                          height: 1.35,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                Icon(Icons.chevron_right, color: _goldDim, size: 20),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
