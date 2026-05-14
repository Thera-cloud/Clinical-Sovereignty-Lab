// =============================================================================
// SENSITIVE CLINICAL PROFILE — INSPECTION FIXTURE
//
// In-memory mock data for the local Flutter dev preview of
// `sensitive_clinical_profile_screen.dart`. Consumed exclusively by
// `sensitive_profile_inspection_harness.dart`, which is itself reachable only
// behind a `kDebugMode` URL gate. These fixtures must NEVER be imported by
// production screens or release-build code paths.
//
// Data shape mirrors the REST contract sealed in Phase 4b
// (GET /api/coach/sensitive-profile/{user_id} + .../log). Dates are computed
// against `DateTime.now()` so the "within 7d" / "8d out" / "past 7d" badge
// + activity-log windows always render as the user expects relative to the
// time the harness is launched. The `enrolled` flag flips the harness between
// "render the populated profile" and "render the screen's error state as
// though the API returned 404 not_enrolled".
// =============================================================================

import '../sensitive_clinical_profile_screen.dart';

/// Wrapper bundling a fully-formed `SensitiveProfile`, a pre-baked activity
/// log, and a `enrolled` flag the harness uses to choose between rendering
/// the profile body and the screen's "not enrolled" error state.
///
/// `notEnrolledError` is the synthetic message the harness pipes into
/// `loadErrorOverride` when `enrolled == false`; it mirrors the wording the
/// real API returns when a non-enrolled user_id is queried.
class SensitiveProfileInspectionFixture {
  final SensitiveProfile profile;
  final List<ActivityEvent> logEvents;
  final bool enrolled;
  final String? notEnrolledError;

  const SensitiveProfileInspectionFixture({
    required this.profile,
    required this.logEvents,
    required this.enrolled,
    this.notEnrolledError,
  });

  /// Enrolled state — covers all 9 sections in non-empty configurations.
  ///
  /// Composition (per inspection brief):
  ///   - 2 active codewords (hash-prefix only, no plaintext)
  ///   - embodiment_phase: 'transitioning'
  ///   - novelty_threshold: 0.25, arousal_threshold: 1.5
  ///   - population_type: 'trafficking_survivor'
  ///   - substance_use_status: 'recovery'
  ///   - 2 polyvictim layers (one high, one moderate)
  ///   - 1 legal status case with next_event_date 8 days out
  ///   - 2 trigger dates (one within 7 days, one farther out)
  ///   - safe_silence_mode_state: 'pending_approval' with codeword precondition met
  ///   - 10 activity log events spanning past 7 days across 5 event types
  static SensitiveProfileInspectionFixture get enrolledFixture {
    final now = DateTime.now().toUtc();
    final iso = (DateTime d) => d.toIso8601String();

    final profile = SensitiveProfile(
      userId: 'audit_client_inspection',
      embodimentPhase: 'transitioning',
      noveltyThreshold: 0.25,
      arousalThreshold: 1.5,
      substanceStatus: 'recovery',
      sexAddictionStatus: null,
      gamblingStatus: 'recovery',
      gamingStatus: null,
      spendingCompulsionStatus: null,
      foodCompulsionStatus: null,
      workCompulsionStatus: null,
      codependencyStatus: null,
      crossAddictionProfile: <String, dynamic>{
        'active_branches': <String>['substance', 'gambling'],
        'notes_redacted': '[redacted: inspection cross-addiction capsule]',
      },
      populationType: 'trafficking_survivor',
      isEnrolled: true,
      coachAuthorized: true,
      safeSilence: SafeSilenceState(
        // Pending approval: a coach has proposed, an admin in a SEPARATE
        // session must approve. Codeword precondition is met (2 active
        // codewords below) so the panel will NOT render the red warning,
        // and the admin-role view of the harness will render the approve
        // form (proposal id is the synthetic uuid below).
        state: 'pending_approval',
        proposerId: 'CoachN',
        proposalId: 'prop_inspect_8e1c4f2a',
        proposedAt: iso(now.subtract(const Duration(hours: 6))),
        approverId: null,
        approvedAt: null,
        // 7-day proposal window (server enforces this; mirror the contract
        // so the surrounding KV table has a non-null Expires-at row).
        expiresAt: iso(now.add(const Duration(days: 7))),
      ),
      codewords: [
        Codeword(
          // Hash prefixes only — never store plaintext in fixtures.
          hashPrefix: '7f3a9c2b',
          codewordType: 'innocuous_phrase',
          codewordLabel: 'lighthouse',
          triggersMandatoryReporting: false,
          setByClinicianId: 'CoachN',
          setAt: iso(now.subtract(const Duration(days: 21))),
          active: true,
          lastTriggeredAt: iso(now.subtract(const Duration(days: 4))),
          triggerCount: 3,
        ),
        Codeword(
          hashPrefix: 'a1b8e054',
          codewordType: 'explicit_word',
          codewordLabel: 'north star',
          triggersMandatoryReporting: true,
          setByClinicianId: 'CoachN',
          setAt: iso(now.subtract(const Duration(days: 9))),
          active: true,
          lastTriggeredAt: null,
          triggerCount: 0,
        ),
      ],
      triggerDates: [
        TriggerDate(
          id: 9001,
          // Inside the today ±7d window → feeds the 'within 7d' red badge
          // on the Trigger Dates section.
          triggerDate: iso(now.add(const Duration(days: 3))),
          dateType: 'court_appearance',
          severity: 'high',
          recurringAnnually: false,
          notesRedacted:
              '[redacted: court date – Polyvictim layer 2 cross-reference]',
          setByClinicianId: 'CoachN',
          setAt: iso(now.subtract(const Duration(days: 14))),
          active: true,
        ),
        TriggerDate(
          id: 9002,
          // Outside the 7d badge window so the section still has variety.
          triggerDate: iso(now.add(const Duration(days: 60))),
          dateType: 'escape_anniversary',
          severity: 'moderate',
          recurringAnnually: true,
          notesRedacted: '[redacted: annual anniversary]',
          setByClinicianId: 'CoachN',
          setAt: iso(now.subtract(const Duration(days: 30))),
          active: true,
        ),
      ],
      polyvictimLayers: [
        PolyvictimLayer(
          id: 7001,
          layerType: 'childhood_abuse',
          severity: 'high', // drives the red Polyvictim badge
          active: true,
          setByClinicianId: 'CoachN',
          setAt: iso(now.subtract(const Duration(days: 28))),
          notesRedacted:
              '[redacted: 3 distinct perpetrator clusters identified]',
        ),
        PolyvictimLayer(
          id: 7002,
          layerType: 'legal_system_trauma',
          severity: 'moderate',
          active: true,
          setByClinicianId: 'CoachN',
          setAt: iso(now.subtract(const Duration(days: 11))),
          notesRedacted: '[redacted: prior provider boundary failure]',
        ),
      ],
      legalStatus: [
        LegalCase(
          id: 5001,
          caseType: 'criminal_against_trafficker',
          caseStatus: 'active_hearing_scheduled',
          // 8 days out → legal badge will say 'event in 8d' (cyan, since >7).
          nextEventDate: iso(now.add(const Duration(days: 8))),
          attorneyContactRedacted: '[redacted: J. Doe, county victim services]',
          setByCaseManagerId: 'CoachN',
          setAt: iso(now.subtract(const Duration(days: 45))),
          active: true,
        ),
      ],
    );

    // 10 activity log events spanning past 7 days, across 5 distinct event
    // types — exercises the row renderer's severity colors and the day-window
    // chip (the 7d default keeps every event in scope).
    final logEvents = <ActivityEvent>[
      ActivityEvent(
        id: 6010,
        eventType: 'codeword_triggered',
        eventSeverity: 'high',
        payloadJson: {'hash_prefix': '7f3a9c2b'},
        decisionSummary:
            'Soft-pause codeword triggered mid-session; routed to Safe Silence proposal.',
        occurredAt: iso(now.subtract(const Duration(hours: 6))),
        recordedBy: 'CoachN',
        accessClassification: 'clinician_and_admin',
      ),
      ActivityEvent(
        id: 6009,
        eventType: 'safe_silence_proposed',
        eventSeverity: 'moderate',
        payloadJson: {'proposal_id': 'prop_inspect_8e1c4f2a'},
        decisionSummary:
            'Coach proposed Safe Silence following codeword. Awaiting admin approval.',
        occurredAt: iso(now.subtract(const Duration(hours: 5, minutes: 45))),
        recordedBy: 'CoachN',
        accessClassification: 'clinician_and_admin',
      ),
      ActivityEvent(
        id: 6008,
        eventType: 'arousal_threshold_exceeded',
        eventSeverity: 'moderate',
        payloadJson: {'observed': 1.78, 'threshold': 1.50},
        decisionSummary:
            'Arousal load exceeded clinician override (1.50). De-escalation cue dispatched.',
        occurredAt: iso(now.subtract(const Duration(days: 1, hours: 2))),
        recordedBy: 'system:linguistic_arousal_load',
        accessClassification: 'clinician_and_admin',
      ),
      ActivityEvent(
        id: 6007,
        eventType: 'embodiment_phase_assessed',
        eventSeverity: 'low',
        payloadJson: {'from': 'repair', 'to': 'transitioning'},
        decisionSummary:
            'Quarterly embodiment review shifted phase repair → transitioning.',
        occurredAt: iso(now.subtract(const Duration(days: 2))),
        recordedBy: 'CoachN',
        accessClassification: 'clinician_and_admin',
      ),
      ActivityEvent(
        id: 6006,
        // Admin-only event — the renderer redacts the body even if the
        // server bug-leaks it (defense-in-depth client redaction).
        eventType: 'admin_audit_review',
        eventSeverity: 'low',
        payloadJson: null,
        decisionSummary: null,
        occurredAt: iso(now.subtract(const Duration(days: 2, hours: 8))),
        recordedBy: 'system:admin_audit',
        accessClassification: 'admin_only_redacted',
      ),
      ActivityEvent(
        id: 6005,
        eventType: 'polyvictim_layer_added',
        eventSeverity: 'high',
        payloadJson: {'layer_type': 'institutional_betrayal'},
        decisionSummary:
            'Layer 2 (institutional_betrayal, moderate) added after disclosure.',
        occurredAt: iso(now.subtract(const Duration(days: 3, hours: 4))),
        recordedBy: 'CoachN',
        accessClassification: 'clinician_and_admin',
      ),
      ActivityEvent(
        id: 6004,
        eventType: 'arousal_threshold_exceeded',
        eventSeverity: 'critical',
        payloadJson: {'observed': 2.31, 'threshold': 1.50},
        decisionSummary:
            'Spike well past clinician override; session paused and clinician paged.',
        occurredAt: iso(now.subtract(const Duration(days: 4, hours: 1))),
        recordedBy: 'system:linguistic_arousal_load',
        accessClassification: 'clinician_and_admin',
      ),
      ActivityEvent(
        id: 6003,
        eventType: 'codeword_triggered',
        eventSeverity: 'moderate',
        payloadJson: {'hash_prefix': '7f3a9c2b'},
        decisionSummary:
            'Soft-pause codeword triggered; agent honored and pivoted to grounding.',
        occurredAt: iso(now.subtract(const Duration(days: 5, hours: 6))),
        recordedBy: 'CoachN',
        accessClassification: 'clinician_and_admin',
      ),
      ActivityEvent(
        id: 6002,
        eventType: 'embodiment_phase_assessed',
        eventSeverity: 'low',
        payloadJson: {'from': null, 'to': 'repair'},
        decisionSummary:
            'Initial embodiment assessment recorded as repair (intake clinician).',
        occurredAt: iso(now.subtract(const Duration(days: 6, hours: 2))),
        recordedBy: 'CoachN',
        accessClassification: 'clinician_and_admin',
      ),
      ActivityEvent(
        id: 6001,
        eventType: 'codeword_triggered',
        eventSeverity: 'low',
        payloadJson: {'hash_prefix': '7f3a9c2b'},
        decisionSummary:
            'Codeword triggered during voice call; auto-redirected to Coach.',
        occurredAt: iso(now.subtract(const Duration(days: 6, hours: 18))),
        recordedBy: 'CoachN',
        accessClassification: 'clinician_and_admin',
      ),
    ];

    return SensitiveProfileInspectionFixture(
      profile: profile,
      logEvents: logEvents,
      enrolled: true,
      notEnrolledError: null,
    );
  }

  /// Not-enrolled state — same `SensitiveProfile` shape as the enrolled
  /// fixture (so the harness has something to fall back to if a future caller
  /// inspects `.profile` directly), but `enrolled = false` and a synthetic
  /// `notEnrolledError` matching the wording the live API returns. The
  /// harness routes this fixture into `loadErrorOverride` so the screen
  /// renders its standard error UI with the Retry affordance.
  static SensitiveProfileInspectionFixture get notEnrolledFixture {
    final base = enrolledFixture;
    return SensitiveProfileInspectionFixture(
      profile: base.profile,
      logEvents: base.logEvents,
      enrolled: false,
      notEnrolledError:
          'API 404: not_enrolled — user has no sensitive clinical profile.',
    );
  }
}
