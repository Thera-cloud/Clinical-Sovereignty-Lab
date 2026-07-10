// =============================================================================
// SENSITIVE CLINICAL PROFILE — Phase 4b Note 3 Flutter Screen
//
// Clinician-facing portal for the Sensitive Clinical Bridge (Plan v1.3).
// Reads /api/coach/sensitive-profile/{user_id} once and renders 9
// collapsed-by-default sections. Section badges are derived from the
// SAME single GET response (Note 1: no N+1 fetches). Activity log
// honors server-side access_classification filtering with paginated
// "load older" (Note 2: hard cap 200 rows per fetch). Threshold sliders
// show the population preset alongside the current value (Note 3).
//
// Sequencing reminder: this screen ships against the REST contract
// sealed in Phase 4b. It does NOT introduce new endpoints. If a UX
// requirement surfaces a missing endpoint, it must come back as a
// Phase 4b extension request — never a quiet REST patch from here.
// =============================================================================

import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

import '../config/app_config.dart' as cfg;

import 'client_cross_addiction_profile_screen.dart';
import 'client_framework_menu_screen.dart';
import 'client_parts_registry_screen.dart';

// -----------------------------------------------------------------------------
// DESIGN TOKENS — mirror settings_screen.dart so visual language is consistent
// across the coach portal.
// -----------------------------------------------------------------------------
class _D {
  static const bgVoid = Color(0xFF050505);
  static const bgCard = Color(0xFF111111);
  static const bgElev = Color(0xFF1A1A1A);
  static const gold = Color(0xFFC9A962);
  static const goldBright = Color(0xFFE8D5A3);
  static const goldDim = Color(0xFF8B7355);
  static const cyan = Color(0xFF4ECDC4);
  static const purple = Color(0xFF9D4EDD);
  static const red = Color(0xFFEF4444);
  static const yellow = Color(0xFFFACC15);
  static const green = Color(0xFF22C55E);
  static const text = Color(0xFFFFFFFF);
  static const textDim = Color(0xFF888888);
  static const border = Color(0xFF252525);
}

// -----------------------------------------------------------------------------
// POPULATION THRESHOLD PRESETS (Note 3)
// Mirror Phase 2A spec; if backend introduces new presets, mirror here AND
// extend `_presetForPopulation`.
// -----------------------------------------------------------------------------
const Map<String, double> _NOVELTY_PRESETS = {
  'trafficking_survivor': 0.20,
  'severe_sexual_trauma': 0.25,
  'general_trauma': 0.30,
  'non_trauma': 0.50,
};

const Map<String, double> _AROUSAL_PRESETS = {
  // Mirror linguistic_arousal_load.py. Held conservatively to match Phase 2A
  // until clinician-tuning UI surfaces real overrides.
  'trafficking_survivor': 0.60,
  'severe_sexual_trauma': 0.80,
  'general_trauma': 1.00,
  'non_trauma': 1.50,
};

double _noveltyPreset(String? populationType) =>
    _NOVELTY_PRESETS[populationType ?? ''] ??
    _NOVELTY_PRESETS['general_trauma']!;
double _arousalPreset(String? populationType) =>
    _AROUSAL_PRESETS[populationType ?? ''] ??
    _AROUSAL_PRESETS['general_trauma']!;

/// Calendar date as YYYY-MM-DD for trigger/legal endpoints.
String _dateOnlyIso(DateTime d) {
  final local = DateTime(d.year, d.month, d.day);
  final y = local.year.toString().padLeft(4, '0');
  final m = local.month.toString().padLeft(2, '0');
  final day = local.day.toString().padLeft(2, '0');
  return '$y-$m-$day';
}

// -----------------------------------------------------------------------------
// Interactive controls — enum mirrors backend sensitive_profile_api.py (Phase 4b).
// -----------------------------------------------------------------------------
const List<String> _kEmbodimentPhases = ['repair', 'transitioning', 'ready'];
const List<String> _kSubstanceStatuses = [
  'none',
  'recovery',
  'active_use',
  'crisis',
];

/// Server CHECK constraint (migration 204): explicit_word | innocuous_phrase.
const List<String> _kCodewordTypesApi = ['explicit_word', 'innocuous_phrase'];
const List<String> _kTriggerDateTypes = [
  'escape_anniversary',
  'first_exploitation',
  'legal_outcome',
  'related_death',
  'custody_outcome',
  'court_appearance',
  'medical_anniversary',
  'other',
];
const List<String> _kSeverities = ['low', 'moderate', 'high', 'critical'];
const List<String> _kPolyvictimLayerTypes = [
  'childhood_abuse',
  'family_dysfunction',
  'prior_partner_violence',
  'trafficking',
  'post_trafficking_exploitation',
  'legal_system_trauma',
  'medical_trauma',
  'religious_trauma',
  'community_violence',
];
const List<String> _kLegalCaseTypes = [
  'criminal_against_trafficker',
  't_visa',
  'u_visa',
  'civil',
  'custody',
  'expungement',
  'protective_order',
  'other',
];
const List<String> _kLegalCaseStatuses = [
  'pending',
  'active_hearing_scheduled',
  'testifying_imminent',
  'deposition_imminent',
  'outcome_pending',
  'closed',
];

// -----------------------------------------------------------------------------
// SAFE SILENCE EXPIRY THRESHOLDS (Gap M)
// red ≤5 days remaining → expiring soon
// yellow ≤10 days remaining → flag in next clinical review
// green otherwise → healthy
// -----------------------------------------------------------------------------
Color _expiryColor(int? daysRemaining) {
  if (daysRemaining == null) return _D.textDim;
  if (daysRemaining <= 5) return _D.red;
  if (daysRemaining <= 10) return _D.yellow;
  return _D.green;
}

// =============================================================================
// MODELS
// =============================================================================

class SensitiveProfile {
  final String userId;
  final String? embodimentPhase;
  final double? noveltyThreshold;
  final double? arousalThreshold;
  final String? substanceStatus;
  final String? sexAddictionStatus;
  final String? gamblingStatus;
  final String? gamingStatus;
  final String? spendingCompulsionStatus;
  final String? foodCompulsionStatus;
  final String? workCompulsionStatus;
  final String? codependencyStatus;

  /// Clinician-maintained cross-addiction capsule (v1.4).
  final Map<String, dynamic> crossAddictionProfile;
  final SafeSilenceState safeSilence;
  final List<Codeword> codewords;
  final List<TriggerDate> triggerDates;
  final List<PolyvictimLayer> polyvictimLayers;
  final List<LegalCase> legalStatus;

  /// Population type drives the threshold presets. Not part of the GET
  /// response surface yet; default to general_trauma per Note 3 banner rule.
  final String? populationType;

  // -------------------------------------------------------------------------
  // PATH-C ENROLLMENT VISIBILITY (M215 + M216)
  // Backend `_load_profile_data` attaches these two flags so the screen
  // can render the not-enrolled banner + coach-initiated enroll button
  // without a second REST round-trip.
  // -------------------------------------------------------------------------
  final bool isEnrolled;
  final bool coachAuthorized;

  SensitiveProfile({
    required this.userId,
    required this.embodimentPhase,
    required this.noveltyThreshold,
    required this.arousalThreshold,
    required this.substanceStatus,
    required this.sexAddictionStatus,
    required this.gamblingStatus,
    required this.gamingStatus,
    required this.spendingCompulsionStatus,
    required this.foodCompulsionStatus,
    required this.workCompulsionStatus,
    required this.codependencyStatus,
    required this.crossAddictionProfile,
    required this.safeSilence,
    required this.codewords,
    required this.triggerDates,
    required this.polyvictimLayers,
    required this.legalStatus,
    required this.populationType,
    this.isEnrolled = true,
    this.coachAuthorized = false,
  });

  factory SensitiveProfile.fromJson(Map<String, dynamic> j) {
    return SensitiveProfile(
      userId: (j['user_id'] ?? '').toString(),
      embodimentPhase: j['embodiment_phase'] as String?,
      noveltyThreshold: _d(j['novelty_threshold']),
      arousalThreshold: _d(j['arousal_threshold']),
      substanceStatus: j['substance_status'] as String?,
      sexAddictionStatus: j['sex_addiction_status'] as String?,
      gamblingStatus: j['gambling_status'] as String?,
      gamingStatus: j['gaming_status'] as String?,
      spendingCompulsionStatus: j['spending_compulsion_status'] as String?,
      foodCompulsionStatus: j['food_compulsion_status'] as String?,
      workCompulsionStatus: j['work_compulsion_status'] as String?,
      codependencyStatus: j['codependency_status'] as String?,
      crossAddictionProfile: j['cross_addiction_profile'] is Map
          ? Map<String, dynamic>.from(
              (j['cross_addiction_profile'] as Map).cast<String, dynamic>(),
            )
          : {},
      safeSilence: SafeSilenceState.fromJson(
        (j['safe_silence_mode_state'] as Map?)?.cast<String, dynamic>() ?? {},
      ),
      codewords: ((j['codewords'] as List?) ?? [])
          .map((e) => Codeword.fromJson((e as Map).cast<String, dynamic>()))
          .toList(),
      triggerDates: ((j['trigger_dates'] as List?) ?? [])
          .map((e) => TriggerDate.fromJson((e as Map).cast<String, dynamic>()))
          .toList(),
      polyvictimLayers: ((j['polyvictim_layers'] as List?) ?? [])
          .map(
            (e) => PolyvictimLayer.fromJson((e as Map).cast<String, dynamic>()),
          )
          .toList(),
      legalStatus: ((j['legal_status'] as List?) ?? [])
          .map((e) => LegalCase.fromJson((e as Map).cast<String, dynamic>()))
          .toList(),
      populationType: j['population_type'] as String?,
      isEnrolled: j['is_enrolled'] == true,
      coachAuthorized: j['coach_sensitive_bridge_authorized'] == true,
    );
  }

  /// Note 1: badge counts/strings derived from the SAME response object.
  int get activeCodewordCount => codewords.where((c) => c.active).length;
  int get activePolyvictimCount =>
      polyvictimLayers.where((p) => p.active).length;
  String? get highestPolyvictimSeverity {
    const order = ['critical', 'high', 'moderate', 'low'];
    for (final lvl in order) {
      if (polyvictimLayers.any((p) => p.active && p.severity == lvl))
        return lvl;
    }
    return null;
  }

  bool get hasUpcomingLegalEvent => _legalDaysToNext() != null;
  int? _legalDaysToNext() {
    final now = DateTime.now().toUtc();
    int? best;
    for (final c in legalStatus) {
      if (!c.active || c.nextEventDate == null) continue;
      final dt = DateTime.tryParse(c.nextEventDate!);
      if (dt == null) continue;
      final days = dt.toUtc().difference(now).inDays;
      if (days < 0 || days > 14) continue;
      if (best == null || days < best) best = days;
    }
    return best;
  }

  int? get nextLegalDays => _legalDaysToNext();

  /// Trigger-date proximity badge: any active date within today ±7 days.
  bool get hasNearbyTriggerDate {
    final today = DateTime.now().toUtc();
    final minDay = today.subtract(const Duration(days: 7));
    final maxDay = today.add(const Duration(days: 7));
    for (final t in triggerDates) {
      if (!t.active) continue;
      final dt = DateTime.tryParse(t.triggerDate);
      if (dt == null) continue;
      // Recurring annually: collapse year to the current year for comparison.
      final candidate = t.recurringAnnually
          ? DateTime.utc(today.year, dt.month, dt.day)
          : dt.toUtc();
      if (!candidate.isBefore(minDay) && !candidate.isAfter(maxDay)) {
        return true;
      }
    }
    return false;
  }

  static double? _d(dynamic v) {
    if (v == null) return null;
    if (v is num) return v.toDouble();
    return double.tryParse(v.toString());
  }
}

class SafeSilenceState {
  /// "inactive" | "pending_approval" | "active"
  final String state;
  final String? proposerId;
  final String? proposalId;
  final String? proposedAt;
  final String? approverId;
  final String? approvedAt;
  final String? expiresAt;

  SafeSilenceState({
    required this.state,
    required this.proposerId,
    required this.proposalId,
    required this.proposedAt,
    required this.approverId,
    required this.approvedAt,
    required this.expiresAt,
  });

  factory SafeSilenceState.fromJson(Map<String, dynamic> j) {
    return SafeSilenceState(
      state: (j['state'] ?? 'inactive').toString(),
      proposerId: j['proposer_id'] as String?,
      proposalId: j['proposal_id'] as String?,
      proposedAt: j['proposed_at'] as String?,
      approverId: j['approver_id'] as String?,
      approvedAt: j['approved_at'] as String?,
      expiresAt: j['expires_at'] as String?,
    );
  }

  bool get isInactive => state == 'inactive';
  bool get isPending => state == 'pending_approval';
  bool get isActive => state == 'active';

  int? get daysUntilExpiry {
    if (!isActive || expiresAt == null) return null;
    final dt = DateTime.tryParse(expiresAt!);
    if (dt == null) return null;
    final delta = dt.toUtc().difference(DateTime.now().toUtc()).inDays;
    return delta < 0 ? 0 : delta;
  }
}

class Codeword {
  final String hashPrefix;
  final String? codewordType;
  final String? codewordLabel;
  final bool triggersMandatoryReporting;
  final String? setByClinicianId;
  final String? setAt;
  final bool active;
  final String? lastTriggeredAt;
  final int triggerCount;

  Codeword({
    required this.hashPrefix,
    required this.codewordType,
    required this.codewordLabel,
    required this.triggersMandatoryReporting,
    required this.setByClinicianId,
    required this.setAt,
    required this.active,
    required this.lastTriggeredAt,
    required this.triggerCount,
  });

  factory Codeword.fromJson(Map<String, dynamic> j) => Codeword(
        hashPrefix: (j['hash_prefix'] ?? '').toString(),
        codewordType: j['codeword_type'] as String?,
        codewordLabel: j['codeword_label'] as String?,
        triggersMandatoryReporting: j['triggers_mandatory_reporting'] == true,
        setByClinicianId: j['set_by_clinician_id'] as String?,
        setAt: j['set_at'] as String?,
        active: j['active'] == true,
        lastTriggeredAt: j['last_triggered_at'] as String?,
        triggerCount: (j['trigger_count'] as num?)?.toInt() ?? 0,
      );
}

class TriggerDate {
  final int id;
  final String triggerDate;
  final String? dateType;
  final String? severity;
  final bool recurringAnnually;
  final String? notesRedacted;
  final String? setByClinicianId;
  final String? setAt;
  final bool active;

  TriggerDate({
    required this.id,
    required this.triggerDate,
    required this.dateType,
    required this.severity,
    required this.recurringAnnually,
    required this.notesRedacted,
    required this.setByClinicianId,
    required this.setAt,
    required this.active,
  });

  factory TriggerDate.fromJson(Map<String, dynamic> j) => TriggerDate(
        id: (j['id'] as num).toInt(),
        triggerDate: (j['trigger_date'] ?? '').toString(),
        dateType: j['date_type'] as String?,
        severity: j['severity'] as String?,
        recurringAnnually: j['recurring_annually'] == true,
        notesRedacted: j['notes_redacted'] as String?,
        setByClinicianId: j['set_by_clinician_id'] as String?,
        setAt: j['set_at'] as String?,
        active: j['active'] == true,
      );
}

class PolyvictimLayer {
  final int id;
  final String layerType;
  final String severity;
  final bool active;
  final String? setByClinicianId;
  final String? setAt;
  final String? notesRedacted;

  PolyvictimLayer({
    required this.id,
    required this.layerType,
    required this.severity,
    required this.active,
    required this.setByClinicianId,
    required this.setAt,
    required this.notesRedacted,
  });

  factory PolyvictimLayer.fromJson(Map<String, dynamic> j) => PolyvictimLayer(
        id: (j['id'] as num).toInt(),
        layerType: (j['layer_type'] ?? '').toString(),
        severity: (j['severity'] ?? 'low').toString(),
        active: j['active'] == true,
        setByClinicianId: j['set_by_clinician_id'] as String?,
        setAt: j['set_at'] as String?,
        notesRedacted: j['notes_redacted'] as String?,
      );
}

class LegalCase {
  final int id;
  final String caseType;
  final String caseStatus;
  final String? nextEventDate;
  final String? attorneyContactRedacted;
  final String? setByCaseManagerId;
  final String? setAt;
  final bool active;

  LegalCase({
    required this.id,
    required this.caseType,
    required this.caseStatus,
    required this.nextEventDate,
    required this.attorneyContactRedacted,
    required this.setByCaseManagerId,
    required this.setAt,
    required this.active,
  });

  factory LegalCase.fromJson(Map<String, dynamic> j) => LegalCase(
        id: (j['id'] as num).toInt(),
        caseType: (j['case_type'] ?? '').toString(),
        caseStatus: (j['case_status'] ?? '').toString(),
        nextEventDate: j['next_event_date'] as String?,
        attorneyContactRedacted: j['attorney_contact_redacted'] as String?,
        setByCaseManagerId: j['set_by_case_manager_id'] as String?,
        setAt: j['set_at'] as String?,
        active: j['active'] == true,
      );
}

class ActivityEvent {
  final int id;
  final String eventType;
  final String? eventSeverity;
  final dynamic payloadJson;
  final String? decisionSummary;
  final String? occurredAt;
  final String? recordedBy;
  final String accessClassification;

  ActivityEvent({
    required this.id,
    required this.eventType,
    required this.eventSeverity,
    required this.payloadJson,
    required this.decisionSummary,
    required this.occurredAt,
    required this.recordedBy,
    required this.accessClassification,
  });

  factory ActivityEvent.fromJson(Map<String, dynamic> j) => ActivityEvent(
        id: (j['id'] as num).toInt(),
        eventType: (j['event_type'] ?? '').toString(),
        eventSeverity: j['event_severity'] as String?,
        payloadJson: j['payload_json'],
        decisionSummary: j['decision_summary'] as String?,
        occurredAt: j['occurred_at'] as String?,
        recordedBy: j['recorded_by'] as String?,
        accessClassification:
            (j['access_classification'] ?? 'clinician_and_admin').toString(),
      );

  /// Defense-in-depth client redaction: even though the server already
  /// blanks payloads for admin_only_redacted (and never sends them to
  /// COACH role principals), we double-check at render time. A bug in
  /// the server cannot leak through this layer.
  bool get isAdminRedacted => accessClassification == 'admin_only_redacted';
}

// =============================================================================
// API CLIENT
// Single source of network truth; all endpoints come through here so a
// future contract change is a single-file diff.
// =============================================================================

class _SensitiveProfileApi {
  final String token;
  _SensitiveProfileApi(this.token);

  String get _base => cfg.AppConfig.apiBaseUrl;

  Map<String, String> get _headers => {
        'Authorization': 'Bearer $token',
        'Content-Type': 'application/json',
      };

  Future<SensitiveProfile> getProfile(String userId) async {
    final uri = Uri.parse('$_base/api/coach/sensitive-profile/$userId');
    final resp = await http
        .get(uri, headers: _headers)
        .timeout(const Duration(seconds: 15));
    if (resp.statusCode != 200) {
      throw _ApiError.fromResponse(resp);
    }
    final data = jsonDecode(resp.body) as Map<String, dynamic>;
    return SensitiveProfile.fromJson(data);
  }

  Future<List<ActivityEvent>> getLog(
    String userId, {
    required int days,
    required int limit,
    int? beforeId,
  }) async {
    final qp = {
      'days': '$days',
      'limit': '$limit',
      if (beforeId != null) 'before_id': '$beforeId',
    };
    final uri = Uri.parse('$_base/api/coach/sensitive-profile/$userId/log')
        .replace(queryParameters: qp);
    final resp = await http
        .get(uri, headers: _headers)
        .timeout(const Duration(seconds: 15));
    if (resp.statusCode != 200) {
      throw _ApiError.fromResponse(resp);
    }
    final data = jsonDecode(resp.body) as Map<String, dynamic>;
    final rows = (data['rows'] as List?) ?? [];
    return rows
        .map((e) => ActivityEvent.fromJson((e as Map).cast<String, dynamic>()))
        .toList();
  }

  Future<void> putThreshold(
    String userId,
    String which,
    double value, {
    String? populationPreset,
  }) async {
    final path = which == 'novelty' ? 'novelty-threshold' : 'arousal-threshold';
    final uri = Uri.parse('$_base/api/coach/sensitive-profile/$userId/$path');
    final Map<String, dynamic> payload = which == 'novelty'
        ? {'novelty_threshold': value}
        : {'arousal_threshold': value};
    if (populationPreset != null && populationPreset.isNotEmpty) {
      payload['population_preset'] = populationPreset;
    }
    final body = jsonEncode(payload);
    final resp = await http
        .put(uri, headers: _headers, body: body)
        .timeout(const Duration(seconds: 10));
    if (resp.statusCode != 200) {
      throw _ApiError.fromResponse(resp);
    }
  }

  Future<void> putEmbodimentPhase(String userId, String phase) async {
    final uri = Uri.parse(
      '$_base/api/coach/sensitive-profile/$userId/embodiment-phase',
    );
    final resp = await http
        .put(
          uri,
          headers: _headers,
          body: jsonEncode({'embodiment_phase': phase}),
        )
        .timeout(const Duration(seconds: 15));
    if (resp.statusCode != 200) {
      throw _ApiError.fromResponse(resp);
    }
  }

  Future<void> putSubstanceStatus(String userId, String status) async {
    final uri = Uri.parse(
      '$_base/api/coach/sensitive-profile/$userId/substance-status',
    );
    final resp = await http
        .put(
          uri,
          headers: _headers,
          body: jsonEncode({'substance_status': status}),
        )
        .timeout(const Duration(seconds: 15));
    if (resp.statusCode != 200) {
      throw _ApiError.fromResponse(resp);
    }
  }

  /// Backend [AddictionBranchStatusUpdate] expects `{"status": "..."}` only.
  /// Allowed server enum: none | recovery | active | crisis (not `active_use`).
  Future<void> _putAddictionStatus(
    String userId,
    String endpointSlug,
    String status,
  ) async {
    final apiStatus = status == 'active_use' ? 'active' : status;
    final uri = Uri.parse(
      '$_base/api/coach/sensitive-profile/$userId/$endpointSlug',
    );
    final resp = await http
        .put(
          uri,
          headers: _headers,
          body: jsonEncode({'status': apiStatus}),
        )
        .timeout(const Duration(seconds: 15));
    if (resp.statusCode != 200) throw _ApiError.fromResponse(resp);
  }

  Future<void> putSexAddictionStatus(String userId, String s) =>
      _putAddictionStatus(userId, 'sex-addiction-status', s);
  Future<void> putGamblingStatus(String userId, String s) =>
      _putAddictionStatus(userId, 'gambling-status', s);
  Future<void> putGamingStatus(String userId, String s) =>
      _putAddictionStatus(userId, 'gaming-status', s);
  Future<void> putSpendingCompulsionStatus(String userId, String s) =>
      _putAddictionStatus(userId, 'spending-compulsion-status', s);
  Future<void> putFoodCompulsionStatus(String userId, String s) =>
      _putAddictionStatus(userId, 'food-compulsion-status', s);
  Future<void> putWorkCompulsionStatus(String userId, String s) =>
      _putAddictionStatus(userId, 'work-compulsion-status', s);
  Future<void> putCodependencyStatus(String userId, String s) =>
      _putAddictionStatus(userId, 'codependency-status', s);

  Future<void> postCodeword(
    String userId, {
    required String plaintextCodeword,
    required String codewordType,
    required bool triggersMandatoryReporting,
    String? codewordLabel,
  }) async {
    final uri =
        Uri.parse('$_base/api/coach/sensitive-profile/$userId/codeword');
    final resp = await http
        .post(
          uri,
          headers: _headers,
          body: jsonEncode({
            'plaintext_codeword': plaintextCodeword,
            'codeword_type': codewordType,
            'triggers_mandatory_reporting': triggersMandatoryReporting,
            if (codewordLabel != null && codewordLabel.isNotEmpty)
              'codeword_label': codewordLabel,
          }),
        )
        .timeout(const Duration(seconds: 15));
    if (resp.statusCode != 200) {
      throw _ApiError.fromResponse(resp);
    }
  }

  Future<void> deleteCodeword(String userId, String hashPrefix) async {
    final uri = Uri.parse(
      '$_base/api/coach/sensitive-profile/$userId/codeword/$hashPrefix',
    );
    final resp = await http
        .delete(uri, headers: _headers)
        .timeout(const Duration(seconds: 15));
    if (resp.statusCode != 200) {
      throw _ApiError.fromResponse(resp);
    }
  }

  Future<void> postTriggerDate(
    String userId, {
    required String triggerDateIso,
    required String dateType,
    required String severity,
    required bool recurringAnnually,
    String? notesRedacted,
  }) async {
    final uri =
        Uri.parse('$_base/api/coach/sensitive-profile/$userId/trigger-date');
    final resp = await http
        .post(
          uri,
          headers: _headers,
          body: jsonEncode({
            'trigger_date': triggerDateIso,
            'date_type': dateType,
            'severity': severity,
            'recurring_annually': recurringAnnually,
            if (notesRedacted != null && notesRedacted.isNotEmpty)
              'notes_redacted': notesRedacted,
          }),
        )
        .timeout(const Duration(seconds: 15));
    if (resp.statusCode != 200) {
      throw _ApiError.fromResponse(resp);
    }
  }

  Future<void> deleteTriggerDate(String userId, int id) async {
    final uri = Uri.parse(
      '$_base/api/coach/sensitive-profile/$userId/trigger-date/$id',
    );
    final resp = await http
        .delete(uri, headers: _headers)
        .timeout(const Duration(seconds: 15));
    if (resp.statusCode != 200) {
      throw _ApiError.fromResponse(resp);
    }
  }

  Future<void> postPolyvictimLayer(
    String userId, {
    required String layerType,
    required String severity,
    String? notesRedacted,
  }) async {
    final uri = Uri.parse(
        '$_base/api/coach/sensitive-profile/$userId/polyvictim-layer');
    final resp = await http
        .post(
          uri,
          headers: _headers,
          body: jsonEncode({
            'layer_type': layerType,
            'severity': severity,
            if (notesRedacted != null && notesRedacted.isNotEmpty)
              'notes_redacted': notesRedacted,
          }),
        )
        .timeout(const Duration(seconds: 15));
    if (resp.statusCode != 200) {
      throw _ApiError.fromResponse(resp);
    }
  }

  Future<void> deletePolyvictimLayer(String userId, int layerId) async {
    final uri = Uri.parse(
      '$_base/api/coach/sensitive-profile/$userId/polyvictim-layer/$layerId',
    );
    final resp = await http
        .delete(uri, headers: _headers)
        .timeout(const Duration(seconds: 15));
    if (resp.statusCode != 200) {
      throw _ApiError.fromResponse(resp);
    }
  }

  /// Approve a pending system-suggested polyvictim layer.
  Future<void> activatePolyvictimLayer(String userId, int layerId) async {
    final uri = Uri.parse(
      '$_base/api/coach/sensitive-profile/$userId/polyvictim-layer/$layerId/activate',
    );
    final resp = await http
        .post(uri, headers: _headers)
        .timeout(const Duration(seconds: 15));
    if (resp.statusCode != 200) {
      throw _ApiError.fromResponse(resp);
    }
  }

  /// Reject/remove a pending system-suggested polyvictim layer.
  Future<void> dismissPolyvictimLayerSuggestion(
      String userId, int layerId) async {
    final uri = Uri.parse(
      '$_base/api/coach/sensitive-profile/$userId/polyvictim-layer/$layerId/dismiss-suggestion',
    );
    final resp = await http
        .delete(uri, headers: _headers)
        .timeout(const Duration(seconds: 15));
    if (resp.statusCode != 200) {
      throw _ApiError.fromResponse(resp);
    }
  }

  Future<void> postLegalStatus(
    String userId, {
    required String caseType,
    required String caseStatus,
    String? nextEventDateIso,
    String? attorneyContactRedacted,
  }) async {
    final uri =
        Uri.parse('$_base/api/coach/sensitive-profile/$userId/legal-status');
    final Map<String, dynamic> body = {
      'case_type': caseType,
      'case_status': caseStatus,
      if (nextEventDateIso != null && nextEventDateIso.isNotEmpty)
        'next_event_date': nextEventDateIso,
      if (attorneyContactRedacted != null && attorneyContactRedacted.isNotEmpty)
        'attorney_contact_redacted': attorneyContactRedacted,
    };
    final resp = await http
        .post(
          uri,
          headers: _headers,
          body: jsonEncode(body),
        )
        .timeout(const Duration(seconds: 15));
    if (resp.statusCode != 200) {
      throw _ApiError.fromResponse(resp);
    }
  }

  Future<void> patchLegalStatus(
    String userId,
    int legalId, {
    String? caseStatus,
    String? nextEventDateIso,
    String? attorneyContactRedacted,
  }) async {
    final uri = Uri.parse(
      '$_base/api/coach/sensitive-profile/$userId/legal-status/$legalId',
    );
    final Map<String, dynamic> patch = {};
    if (caseStatus != null) patch['case_status'] = caseStatus;
    if (nextEventDateIso != null && nextEventDateIso.isNotEmpty) {
      patch['next_event_date'] = nextEventDateIso;
    }
    if (attorneyContactRedacted != null) {
      patch['attorney_contact_redacted'] = attorneyContactRedacted;
    }
    if (patch.isEmpty) {
      throw _ApiError(422, 'no_fields_to_patch');
    }
    final resp = await http
        .patch(uri, headers: _headers, body: jsonEncode(patch))
        .timeout(const Duration(seconds: 15));
    if (resp.statusCode != 200) {
      throw _ApiError.fromResponse(resp);
    }
  }

  Future<void> deleteSafeSilence(String userId) async {
    final uri =
        Uri.parse('$_base/api/coach/sensitive-profile/$userId/safe-silence');
    final resp = await http
        .delete(uri, headers: _headers)
        .timeout(const Duration(seconds: 15));
    if (resp.statusCode != 200) {
      throw _ApiError.fromResponse(resp);
    }
  }

  Future<Map<String, dynamic>> proposeSafeSilence(
    String userId, {
    required String reasonRedacted,
  }) async {
    final uri = Uri.parse(
      '$_base/api/coach/sensitive-profile/$userId/safe-silence/propose',
    );
    final resp = await http
        .post(
          uri,
          headers: _headers,
          body: jsonEncode({'reason_redacted': reasonRedacted}),
        )
        .timeout(const Duration(seconds: 15));
    if (resp.statusCode != 200) {
      throw _ApiError.fromResponse(resp);
    }
    return jsonDecode(resp.body) as Map<String, dynamic>;
  }

  Future<void> approveSafeSilence(
    String userId, {
    required String proposalId,
    String? approverNoteRedacted,
  }) async {
    final uri = Uri.parse(
      '$_base/api/admin/sensitive-profile/$userId/safe-silence/approve',
    );
    final resp = await http
        .post(
          uri,
          headers: _headers,
          body: jsonEncode({
            'proposal_id': proposalId,
            if (approverNoteRedacted != null)
              'approver_note_redacted': approverNoteRedacted,
          }),
        )
        .timeout(const Duration(seconds: 15));
    if (resp.statusCode != 200) {
      throw _ApiError.fromResponse(resp);
    }
  }

  /// Path-C: coach-initiated self-enrollment.
  /// Returns the parsed body on 200; throws _ApiError carrying the
  /// server-side `reason` (`consent_required`, `requires_guardian_consent`,
  /// `already_enrolled`, `not_found`, …) so the caller can render
  /// reason-specific UX.
  Future<Map<String, dynamic>> enrollClient(
    String userId, {
    required String cohortLabel,
    required String populationType,
    required bool informedConsentConfirmed,
  }) async {
    final uri = Uri.parse('$_base/api/coach/sensitive-profile/$userId/enroll');
    final resp = await http
        .post(
          uri,
          headers: _headers,
          body: jsonEncode({
            'cohort_label': cohortLabel,
            'population_type': populationType,
            'informed_consent_confirmed': informedConsentConfirmed,
          }),
        )
        .timeout(const Duration(seconds: 15));
    if (resp.statusCode != 200) {
      throw _ApiError.fromResponse(resp);
    }
    final j = jsonDecode(resp.body);
    if (j is Map<String, dynamic>) return j;
    return <String, dynamic>{};
  }
}

class _ApiError implements Exception {
  final int status;
  final String message;
  final Map<String, dynamic>? detail;

  _ApiError(this.status, this.message, {this.detail});

  factory _ApiError.fromResponse(http.Response resp) {
    final raw = resp.body;
    try {
      final j = jsonDecode(raw);
      if (j is Map<String, dynamic>) {
        final d = j['detail'];
        if (d is Map<String, dynamic>) {
          final reason = d['reason']?.toString() ?? 'request_failed';
          final buf = StringBuffer(reason);
          if (d['pattern_matched'] != null) {
            buf.write(
              ' · pattern "${d['pattern_matched']}" at position ${d['field_position']}',
            );
          }
          if (d['field'] != null) buf.write(' · field: ${d['field']}');
          return _ApiError(resp.statusCode, buf.toString(), detail: d);
        }
        if (d != null) {
          return _ApiError(resp.statusCode, d.toString());
        }
      }
    } catch (_) {}
    final truncated = raw.length > 480 ? '${raw.substring(0, 480)}…' : raw;
    return _ApiError(resp.statusCode,
        truncated.isEmpty ? 'HTTP ${resp.statusCode}' : truncated);
  }

  /// Enrollment / snackbar paths still read `.reason`.
  String get reason => message;

  @override
  String toString() => 'API $status: $message';
}

// =============================================================================
// MAIN SCREEN
// =============================================================================

class SensitiveClinicalProfileScreen extends StatefulWidget {
  /// The clinician/admin opening the screen. Must contain `token` and
  /// `role` (COACH or ADMIN).
  final Map<String, dynamic> currentUserProfile;

  /// Username of the survivor whose sensitive profile is being viewed.
  /// Routes resolve this string against `users.username`.
  final String targetUserId;

  // ---------------------------------------------------------------------------
  // INSPECTION-HARNESS OVERRIDES (additive, null in production)
  //
  // These three parameters exist solely so the local Flutter dev preview at
  // `mobile/lib/screens/inspection/sensitive_profile_inspection_harness.dart`
  // can render this screen against in-memory fixtures without touching the
  // real `_loadProfile()` / `_loadActivityLog()` REST calls. When all three
  // are null (the only production code path), the screen behaves byte-for-byte
  // as before: `initState` triggers `_loadProfile()` which hits the API,
  // which then triggers `_loadActivityLog(reset: true)`.
  //
  // Contract:
  //   - profileOverride non-null   → skip GET /api/coach/sensitive-profile/{id}
  //   - logEventsOverride non-null → skip GET /api/coach/sensitive-profile/{id}/log
  //   - loadErrorOverride non-null → render the error UI as if the GET 4xx'd
  //
  // The harness MUST only be reachable behind a `kDebugMode` URL gate; release
  // builds never expose a code path that supplies these overrides.
  // ---------------------------------------------------------------------------
  final SensitiveProfile? profileOverride;
  final List<ActivityEvent>? logEventsOverride;
  final String? loadErrorOverride;

  /// Coach Command briefings open this screen over [showModalBottomSheet]; pop
  /// twice on exit so back returns to the tab, not the sheet only.
  final bool closeBriefSheetOnExit;

  const SensitiveClinicalProfileScreen({
    super.key,
    required this.currentUserProfile,
    required this.targetUserId,
    this.profileOverride,
    this.logEventsOverride,
    this.loadErrorOverride,
    this.closeBriefSheetOnExit = false,
  });

  @override
  State<SensitiveClinicalProfileScreen> createState() =>
      _SensitiveClinicalProfileScreenState();
}

class _SensitiveClinicalProfileScreenState
    extends State<SensitiveClinicalProfileScreen> {
  late final _SensitiveProfileApi _api;
  SensitiveProfile? _profile;
  String? _loadError;
  bool _loading = true;

  // Activity log pagination state. Server caps at 200 per Note 2(b);
  // we request 200 explicitly so we always get the maximum window per call.
  static const int _logPageSize = 200;
  static const int _logDefaultDays = 7;
  int _logDays = _logDefaultDays;
  final List<ActivityEvent> _logEvents = [];
  bool _logLoading = false;
  String? _logError;
  int? _logCursor; // before_id for next page
  bool _logExhausted = false;

  // PATH-C enrollment state. Drives the disabled state of the
  // "Enroll this client" button so we don't fire two POSTs back-to-back.
  bool _enrollInFlight = false;

  bool _savingEmbodiment = false;
  String? _embodimentInlineError;
  bool _savingSubstance = false;
  String? _substanceInlineError;
  bool _savingSexAddiction = false;
  String? _sexAddictionInlineError;
  bool _savingGambling = false;
  String? _gamblingInlineError;
  bool _savingGaming = false;
  String? _gamingInlineError;
  bool _savingSpendingCompulsion = false;
  String? _spendingCompulsionInlineError;
  bool _savingFoodCompulsion = false;
  String? _foodCompulsionInlineError;
  bool _savingWorkCompulsion = false;
  String? _workCompulsionInlineError;
  bool _savingCodependency = false;
  String? _codependencyInlineError;

  @override
  void initState() {
    super.initState();
    final token = (widget.currentUserProfile['token'] ?? '').toString();
    _api = _SensitiveProfileApi(token);
    _loadProfile();
  }

  String get _role =>
      (widget.currentUserProfile['role'] ?? '').toString().toUpperCase();
  bool get _isAdmin => _role == 'ADMIN';

  /// Debug harness loads fixture via profileOverride — never hit prod APIs.
  bool get _inspectionHarness => widget.profileOverride != null;

  bool _canEditSensitiveFields(SensitiveProfile p) =>
      p.coachAuthorized && p.isEnrolled;

  bool get _blockHarnessNetwork => _inspectionHarness;

  String get _currentPrincipalUsername =>
      (widget.currentUserProfile['username'] ?? '').toString();

  Future<void> _profileRefresh() => _loadProfile();

  Future<void> _loadProfile() async {
    setState(() {
      _loading = true;
      _loadError = null;
    });

    // ---- Inspection-harness short-circuit (additive, null in production) ----
    // When the harness injects overrides we never touch the network. The
    // override branches are only reachable when the screen was constructed
    // from `sensitive_profile_inspection_harness.dart`, which itself is only
    // pushable from a `kDebugMode` URL gate — release builds cannot reach
    // this branch.
    if (widget.loadErrorOverride != null) {
      if (!mounted) return;
      setState(() {
        _loadError = widget.loadErrorOverride;
        _loading = false;
      });
      return;
    }
    if (widget.profileOverride != null) {
      if (!mounted) return;
      setState(() {
        _profile = widget.profileOverride;
        _loading = false;
      });
      _loadActivityLog(reset: true);
      return;
    }

    try {
      final p = await _api.getProfile(widget.targetUserId);
      if (!mounted) return;
      setState(() {
        _profile = p;
        _loading = false;
      });
      // Eagerly fetch the first activity-log page so the badge in the
      // collapsed log section can show row count.
      _loadActivityLog(reset: true);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loadError = e.toString();
        _loading = false;
      });
    }
  }

  Future<void> _loadActivityLog({required bool reset}) async {
    if (_logLoading) return;
    setState(() {
      _logLoading = true;
      _logError = null;
      if (reset) {
        _logEvents.clear();
        _logCursor = null;
        _logExhausted = false;
      }
    });

    // ---- Inspection-harness short-circuit (additive, null in production) ----
    // The harness ships a pre-baked event list; treat it as a single,
    // exhausted page so the "load older" affordance correctly hides.
    if (widget.logEventsOverride != null) {
      if (!mounted) return;
      setState(() {
        if (reset) {
          _logEvents
            ..clear()
            ..addAll(widget.logEventsOverride!);
        }
        _logCursor = _logEvents.isNotEmpty ? _logEvents.last.id : null;
        _logExhausted = true;
        _logLoading = false;
      });
      return;
    }

    try {
      final events = await _api.getLog(
        widget.targetUserId,
        days: _logDays,
        limit: _logPageSize,
        beforeId: _logCursor,
      );
      if (!mounted) return;
      setState(() {
        _logEvents.addAll(events);
        _logCursor = events.isNotEmpty ? events.last.id : _logCursor;
        _logExhausted = events.length < _logPageSize;
        _logLoading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _logError = e.toString();
        _logLoading = false;
      });
    }
  }

  // ---------------------------------------------------------------------------
  // BUILD
  // ---------------------------------------------------------------------------

  void _exitSensitiveRoute() {
    final nav = Navigator.of(context);
    nav.pop();
    if (widget.closeBriefSheetOnExit && nav.canPop()) nav.pop();
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: !widget.closeBriefSheetOnExit,
      onPopInvokedWithResult: (didPop, _) {
        if (didPop || !widget.closeBriefSheetOnExit) return;
        _exitSensitiveRoute();
      },
      child: Scaffold(
        backgroundColor: _D.bgVoid,
        appBar: AppBar(
          backgroundColor: _D.bgCard,
          elevation: 0,
          leading: IconButton(
            tooltip: 'Back',
            icon: const Icon(Icons.arrow_back, color: _D.gold),
            onPressed: _exitSensitiveRoute,
          ),
          title: Text(
            'Sensitive Profile · ${widget.targetUserId}',
            style: const TextStyle(color: _D.gold, fontSize: 16),
          ),
          actions: [
            PopupMenuButton<String>(
              tooltip: 'More',
              icon: const Icon(Icons.more_vert, color: _D.gold),
              onSelected: (v) {
                if (!mounted) return;
                if (v == 'parts') {
                  Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) => ClientPartsRegistryScreen(
                        currentUserProfile: widget.currentUserProfile,
                        targetUserId: widget.targetUserId,
                      ),
                    ),
                  );
                } else if (v == 'framework') {
                  Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) => ClientFrameworkMenuScreen(
                        currentUserProfile: widget.currentUserProfile,
                        targetUserId: widget.targetUserId,
                      ),
                    ),
                  );
                } else if (v == 'cross') {
                  Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) => ClientCrossAddictionProfileScreen(
                        currentUserProfile: widget.currentUserProfile,
                        targetUserId: widget.targetUserId,
                      ),
                    ),
                  );
                }
              },
              itemBuilder: (ctx) => const [
                PopupMenuItem(value: 'parts', child: Text('Parts registry')),
                PopupMenuItem(
                    value: 'framework', child: Text('Framework menu')),
                PopupMenuItem(
                    value: 'cross', child: Text('Cross-addiction profile')),
              ],
            ),
            IconButton(
              tooltip: 'Refresh',
              icon: const Icon(Icons.refresh, color: _D.gold),
              onPressed: _loading ? null : _loadProfile,
            ),
          ],
        ),
        body: _buildBody(),
      ),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator(color: _D.gold));
    }
    if (_loadError != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.error_outline, color: _D.red, size: 48),
              const SizedBox(height: 12),
              Text(
                _loadError!,
                style: const TextStyle(color: _D.text),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 16),
              ElevatedButton(
                style: ElevatedButton.styleFrom(backgroundColor: _D.bgElev),
                onPressed: _loadProfile,
                child: const Text('Retry', style: TextStyle(color: _D.gold)),
              ),
            ],
          ),
        ),
      );
    }
    final p = _profile!;
    return SingleChildScrollView(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // PATH-C: not-enrolled banner. Renders ONLY when the server
          // says is_enrolled=false. The "Enroll this client" button
          // inside the banner only shows for coaches whose
          // coach_sensitive_bridge_authorized flag is true.
          if (!p.isEnrolled)
            _NotEnrolledBanner(
              coachAuthorized: p.coachAuthorized,
              enrollInFlight: _enrollInFlight,
              onEnrollPressed: _openEnrollmentDialog,
            ),
          if (p.populationType == null) const _PopulationTypeBanner(),
          _SectionCard(
            title: 'Embodiment Phase',
            badge: _embodimentBadge(p.embodimentPhase),
            child: _embodimentBody(p),
          ),
          _SectionCard(
            title: 'Thresholds',
            badge: _thresholdsBadge(p),
            child: _thresholdsBody(p),
          ),
          _SectionCard(
            title: 'Substance Status',
            badge: _substanceBadge(p.substanceStatus),
            child: _substanceBody(p),
          ),
          _SectionCard(
            title: 'Sex Addiction',
            badge: _substanceBadge(p.sexAddictionStatus),
            child: _addictionBody(
              p,
              p.sexAddictionStatus,
              'Sex addiction status',
              _savingSexAddiction,
              _sexAddictionInlineError,
              (v) => _applyAddictionStatus(
                v,
                _api.putSexAddictionStatus,
                (b) => setState(() => _savingSexAddiction = b),
                (e) => setState(() => _sexAddictionInlineError = e),
              ),
            ),
          ),
          _SectionCard(
            title: 'Gambling',
            badge: _substanceBadge(p.gamblingStatus),
            child: _addictionBody(
              p,
              p.gamblingStatus,
              'Gambling status',
              _savingGambling,
              _gamblingInlineError,
              (v) => _applyAddictionStatus(
                v,
                _api.putGamblingStatus,
                (b) => setState(() => _savingGambling = b),
                (e) => setState(() => _gamblingInlineError = e),
              ),
            ),
          ),
          _SectionCard(
            title: 'Gaming',
            badge: _substanceBadge(p.gamingStatus),
            child: _addictionBody(
              p,
              p.gamingStatus,
              'Gaming status',
              _savingGaming,
              _gamingInlineError,
              (v) => _applyAddictionStatus(
                v,
                _api.putGamingStatus,
                (b) => setState(() => _savingGaming = b),
                (e) => setState(() => _gamingInlineError = e),
              ),
            ),
          ),
          _SectionCard(
            title: 'Spending Compulsion',
            badge: _substanceBadge(p.spendingCompulsionStatus),
            child: _addictionBody(
              p,
              p.spendingCompulsionStatus,
              'Spending compulsion status',
              _savingSpendingCompulsion,
              _spendingCompulsionInlineError,
              (v) => _applyAddictionStatus(
                v,
                _api.putSpendingCompulsionStatus,
                (b) => setState(() => _savingSpendingCompulsion = b),
                (e) => setState(() => _spendingCompulsionInlineError = e),
              ),
            ),
          ),
          _SectionCard(
            title: 'Food Compulsion',
            badge: _substanceBadge(p.foodCompulsionStatus),
            child: _addictionBody(
              p,
              p.foodCompulsionStatus,
              'Food compulsion status',
              _savingFoodCompulsion,
              _foodCompulsionInlineError,
              (v) => _applyAddictionStatus(
                v,
                _api.putFoodCompulsionStatus,
                (b) => setState(() => _savingFoodCompulsion = b),
                (e) => setState(() => _foodCompulsionInlineError = e),
              ),
            ),
          ),
          _SectionCard(
            title: 'Work Compulsion',
            badge: _substanceBadge(p.workCompulsionStatus),
            child: _addictionBody(
              p,
              p.workCompulsionStatus,
              'Work compulsion status',
              _savingWorkCompulsion,
              _workCompulsionInlineError,
              (v) => _applyAddictionStatus(
                v,
                _api.putWorkCompulsionStatus,
                (b) => setState(() => _savingWorkCompulsion = b),
                (e) => setState(() => _workCompulsionInlineError = e),
              ),
            ),
          ),
          _SectionCard(
            title: 'Codependency',
            badge: _substanceBadge(p.codependencyStatus),
            child: _addictionBody(
              p,
              p.codependencyStatus,
              'Codependency status',
              _savingCodependency,
              _codependencyInlineError,
              (v) => _applyAddictionStatus(
                v,
                _api.putCodependencyStatus,
                (b) => setState(() => _savingCodependency = b),
                (e) => setState(() => _codependencyInlineError = e),
              ),
            ),
          ),
          _SectionCard(
            title: 'Codewords',
            badge: _codewordBadge(p),
            child: _codewordBody(p),
          ),
          _SectionCard(
            title: 'Trigger Dates',
            badge: _triggerDateBadge(p),
            child: _triggerDateBody(p),
          ),
          _SectionCard(
            title: 'Polyvictim Layers',
            badge: _polyvictimBadge(p),
            child: _polyvictimBody(p),
          ),
          _SectionCard(
            title: 'Legal Status',
            badge: _legalBadge(p),
            child: _legalBody(p),
          ),
          _SectionCard(
            title: 'Safe Silence Mode',
            badge: _safeSilenceBadge(p.safeSilence),
            child: _safeSilenceBody(p),
          ),
          _SectionCard(
            title: 'Activity Log',
            badge: _activityLogBadge(),
            child: _activityLogBody(),
          ),
          const SizedBox(height: 32),
        ],
      ),
    );
  }

  // ---------------------------------------------------------------------------
  // BADGES (Note 1 — driven entirely from in-memory _profile, no extra fetch)
  // ---------------------------------------------------------------------------

  Widget? _embodimentBadge(String? phase) {
    if (phase == null || phase == 'ready') return null;
    return _Badge(label: phase, color: _D.cyan);
  }

  Widget? _thresholdsBadge(SensitiveProfile p) {
    final preset = _noveltyPreset(p.populationType);
    final cur = p.noveltyThreshold ?? preset;
    if ((cur - preset).abs() < 1e-6) return null;
    return _Badge(label: 'overridden', color: _D.purple);
  }

  Widget? _substanceBadge(String? status) {
    if (status == null || status == 'none') return null;
    final color = (status == 'crisis' ||
            status == 'active_use' ||
            status == 'active')
        ? _D.red
        : _D.cyan;
    return _Badge(label: status, color: color);
  }

  Widget? _codewordBadge(SensitiveProfile p) {
    final n = p.activeCodewordCount;
    if (n == 0) return null;
    return _Badge(label: '$n active', color: _D.gold);
  }

  Widget? _triggerDateBadge(SensitiveProfile p) {
    if (!p.hasNearbyTriggerDate) return null;
    return _Badge(label: 'within 7d', color: _D.red);
  }

  Widget? _polyvictimBadge(SensitiveProfile p) {
    final n = p.activePolyvictimCount;
    if (n == 0) return null;
    final sev = p.highestPolyvictimSeverity;
    final color = (sev == 'critical' || sev == 'high') ? _D.red : _D.gold;
    final label = sev == null ? '$n layers' : '$n · $sev';
    return _Badge(label: label, color: color);
  }

  Widget? _legalBadge(SensitiveProfile p) {
    final days = p.nextLegalDays;
    if (days == null) return null;
    final color = days <= 3 ? _D.red : (days <= 7 ? _D.yellow : _D.cyan);
    return _Badge(label: 'event in ${days}d', color: color);
  }

  Widget? _safeSilenceBadge(SafeSilenceState s) {
    if (s.isInactive) return null;
    if (s.isActive) {
      final d = s.daysUntilExpiry;
      final c = _expiryColor(d);
      final label = d == null ? 'active' : 'active · ${d}d';
      return _Badge(label: label, color: c);
    }
    return _Badge(label: s.state, color: _D.yellow);
  }

  Widget? _activityLogBadge() {
    if (_logEvents.isEmpty) return null;
    final shown = _logEvents.length;
    return _Badge(label: '$shown rows · ${_logDays}d', color: _D.cyan);
  }

  // ---------------------------------------------------------------------------
  // BODIES
  // ---------------------------------------------------------------------------

  String _apiErrorMessage(Object e) {
    if (e is _ApiError) return e.message;
    return e.toString();
  }

  Future<bool> _confirmDialog({
    required String title,
    required String message,
    String confirmLabel = 'Confirm',
  }) async {
    final ok = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => CallbackShortcuts(
        bindings: <ShortcutActivator, VoidCallback>{
          const SingleActivator(LogicalKeyboardKey.escape): () {
            Navigator.of(ctx).pop(false);
          },
        },
        child: Focus(
          autofocus: true,
          child: AlertDialog(
            backgroundColor: _D.bgCard,
            title: Text(title, style: const TextStyle(color: _D.gold)),
            content: Text(message, style: const TextStyle(color: _D.text)),
            actions: [
              TextButton(
                onPressed: () => Navigator.of(ctx).pop(false),
                child: const Text('Cancel'),
              ),
              TextButton(
                onPressed: () => Navigator.of(ctx).pop(true),
                child: Text(confirmLabel),
              ),
            ],
          ),
        ),
      ),
    );
    return ok == true;
  }

  bool _harnessMutationBarrier() {
    if (!_blockHarnessNetwork) return false;
    if (!mounted) return true;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        backgroundColor: _D.bgElev,
        content: Text(
          'Inspection harness: network mutation skipped.',
          style: TextStyle(color: _D.gold),
        ),
      ),
    );
    return true;
  }

  Widget _embodimentBody(SensitiveProfile p) {
    final rows = <_Kv>[
      const _Kv('Allowed values', 'repair · transitioning · ready'),
    ];
    if (!_canEditSensitiveFields(p)) {
      rows.insert(0, _Kv('Current phase', p.embodimentPhase ?? '—'));
      return _ReadOnlyKv(rows: rows);
    }

    final opts = List<String>.from(_kEmbodimentPhases);
    final cur = p.embodimentPhase;
    if (cur != null && cur.isNotEmpty && !opts.contains(cur)) {
      opts.insert(0, cur);
    }
    final effective = (cur != null && opts.contains(cur)) ? cur : opts.first;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _ReadOnlyKv(rows: rows),
        const SizedBox(height: 8),
        Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Expanded(
              child: DropdownButtonFormField<String>(
                value: effective,
                dropdownColor: _D.bgElev,
                style: const TextStyle(color: _D.text, fontSize: 13),
                decoration: const InputDecoration(
                  filled: true,
                  fillColor: _D.bgElev,
                  border: OutlineInputBorder(),
                  labelText: 'Embodiment phase',
                  labelStyle: TextStyle(color: _D.textDim, fontSize: 12),
                ),
                items: opts
                    .map(
                      (e) => DropdownMenuItem(
                        value: e,
                        child: Text(e, style: const TextStyle(color: _D.text)),
                      ),
                    )
                    .toList(),
                onChanged: _savingEmbodiment
                    ? null
                    : (v) {
                        if (v == null || v == cur) return;
                        _applyEmbodimentPhase(v);
                      },
              ),
            ),
            if (_savingEmbodiment)
              const Padding(
                padding: EdgeInsets.only(left: 10),
                child: SizedBox(
                  width: 22,
                  height: 22,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              ),
          ],
        ),
        if (_embodimentInlineError != null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              _embodimentInlineError!,
              style: const TextStyle(color: _D.red, fontSize: 11),
            ),
          ),
      ],
    );
  }

  Future<void> _applyEmbodimentPhase(String phase) async {
    if (_harnessMutationBarrier()) return;
    setState(() {
      _savingEmbodiment = true;
      _embodimentInlineError = null;
    });
    try {
      await _api.putEmbodimentPhase(widget.targetUserId, phase);
      if (!mounted) return;
      await _loadProfile();
    } catch (e) {
      if (mounted) {
        setState(() => _embodimentInlineError = _apiErrorMessage(e));
      }
    } finally {
      if (mounted) setState(() => _savingEmbodiment = false);
    }
  }

  Widget _thresholdsBody(SensitiveProfile p) {
    final pop = p.populationType;
    if (!_canEditSensitiveFields(p)) {
      final n = p.noveltyThreshold ?? _noveltyPreset(pop);
      final a = p.arousalThreshold ?? _arousalPreset(pop);
      return _ReadOnlyKv(rows: [
        _Kv('Novelty threshold', n.toStringAsFixed(2)),
        _Kv('Arousal threshold', a.toStringAsFixed(2)),
        _Kv('Population preset', pop ?? 'general_trauma'),
      ]);
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _PresetSlider(
          label: 'Novelty threshold',
          value: p.noveltyThreshold ?? _noveltyPreset(pop),
          preset: _noveltyPreset(pop),
          min: 0.0,
          max: 1.0,
          population: pop,
          interactive: true,
          onCommit: (v) => _commitThreshold('novelty', v),
        ),
        const SizedBox(height: 12),
        _PresetSlider(
          label: 'Arousal threshold',
          value: p.arousalThreshold ?? _arousalPreset(pop),
          preset: _arousalPreset(pop),
          min: 0.0,
          max: 3.0,
          population: pop,
          interactive: true,
          onCommit: (v) => _commitThreshold('arousal', v),
        ),
      ],
    );
  }

  Future<void> _commitThreshold(String which, double value) async {
    if (_blockHarnessNetwork) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          backgroundColor: _D.bgElev,
          content: Text(
            'Inspection harness: $which threshold commit skipped (no network).',
            style: const TextStyle(color: _D.gold),
          ),
        ),
      );
      return;
    }
    final pop = _profile?.populationType;
    try {
      await _api.putThreshold(
        widget.targetUserId,
        which,
        value,
        populationPreset: pop,
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          backgroundColor: _D.bgElev,
          content: Text(
            '$which threshold updated to ${value.toStringAsFixed(2)}',
            style: const TextStyle(color: _D.gold),
          ),
        ),
      );
      _loadProfile();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          backgroundColor: _D.red,
          content: Text(
            _apiErrorMessage(e),
            style: const TextStyle(color: Colors.white),
          ),
        ),
      );
    }
  }

  Widget _substanceBody(SensitiveProfile p) {
    final rows = <_Kv>[
      const _Kv('Allowed values', 'none · recovery · active_use · crisis'),
    ];
    if (!_canEditSensitiveFields(p)) {
      rows.insert(0, _Kv('Current status', p.substanceStatus ?? 'none'));
      return _ReadOnlyKv(rows: rows);
    }

    final opts = List<String>.from(_kSubstanceStatuses);
    final cur = p.substanceStatus ?? 'none';
    if (!opts.contains(cur)) {
      opts.insert(0, cur);
    }
    final effective = opts.contains(cur) ? cur : opts.first;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _ReadOnlyKv(rows: rows),
        const SizedBox(height: 8),
        Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Expanded(
              child: DropdownButtonFormField<String>(
                value: effective,
                dropdownColor: _D.bgElev,
                style: const TextStyle(color: _D.text, fontSize: 13),
                decoration: const InputDecoration(
                  filled: true,
                  fillColor: _D.bgElev,
                  border: OutlineInputBorder(),
                  labelText: 'Substance status',
                  labelStyle: TextStyle(color: _D.textDim, fontSize: 12),
                ),
                items: opts
                    .map(
                      (e) => DropdownMenuItem(
                        value: e,
                        child: Text(e, style: const TextStyle(color: _D.text)),
                      ),
                    )
                    .toList(),
                onChanged: _savingSubstance
                    ? null
                    : (v) {
                        if (v == null || v == cur) return;
                        _applySubstanceStatus(v);
                      },
              ),
            ),
            if (_savingSubstance)
              const Padding(
                padding: EdgeInsets.only(left: 10),
                child: SizedBox(
                  width: 22,
                  height: 22,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              ),
          ],
        ),
        if (_substanceInlineError != null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              _substanceInlineError!,
              style: const TextStyle(color: _D.red, fontSize: 11),
            ),
          ),
      ],
    );
  }

  Future<void> _applySubstanceStatus(String status) async {
    if (_harnessMutationBarrier()) return;
    setState(() {
      _savingSubstance = true;
      _substanceInlineError = null;
    });
    try {
      await _api.putSubstanceStatus(widget.targetUserId, status);
      if (!mounted) return;
      await _loadProfile();
    } catch (e) {
      if (mounted) {
        setState(() => _substanceInlineError = _apiErrorMessage(e));
      }
    } finally {
      if (mounted) setState(() => _savingSubstance = false);
    }
  }

  Widget _addictionBody(
    SensitiveProfile p,
    String? currentStatus,
    String label,
    bool saving,
    String? inlineError,
    ValueChanged<String> onChanged,
  ) {
    final rows = <_Kv>[
      const _Kv('Allowed values', 'none · recovery · active_use · crisis'),
    ];
    if (!_canEditSensitiveFields(p)) {
      rows.insert(0, _Kv('Current status', currentStatus ?? 'none'));
      return _ReadOnlyKv(rows: rows);
    }

    final opts = List<String>.from(_kSubstanceStatuses);
    final cur = currentStatus ?? 'none';
    if (!opts.contains(cur)) opts.insert(0, cur);
    final effective = opts.contains(cur) ? cur : opts.first;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _ReadOnlyKv(rows: rows),
        const SizedBox(height: 8),
        Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Expanded(
              child: DropdownButtonFormField<String>(
                value: effective,
                dropdownColor: _D.bgElev,
                style: const TextStyle(color: _D.text, fontSize: 13),
                decoration: InputDecoration(
                  filled: true,
                  fillColor: _D.bgElev,
                  border: const OutlineInputBorder(),
                  labelText: label,
                  labelStyle: const TextStyle(color: _D.textDim, fontSize: 12),
                ),
                items: opts
                    .map(
                      (e) => DropdownMenuItem(
                        value: e,
                        child: Text(e, style: const TextStyle(color: _D.text)),
                      ),
                    )
                    .toList(),
                onChanged: saving
                    ? null
                    : (v) {
                        if (v == null || v == cur) return;
                        onChanged(v);
                      },
              ),
            ),
            if (saving)
              const Padding(
                padding: EdgeInsets.only(left: 10),
                child: SizedBox(
                  width: 22,
                  height: 22,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              ),
          ],
        ),
        if (inlineError != null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              inlineError,
              style: const TextStyle(color: _D.red, fontSize: 11),
            ),
          ),
      ],
    );
  }

  Future<void> _applyAddictionStatus(
    String status,
    Future<void> Function(String userId, String s) apiCall,
    ValueChanged<bool> setSaving,
    ValueChanged<String?> setError,
  ) async {
    if (_harnessMutationBarrier()) return;
    setSaving(true);
    setError(null);
    try {
      await apiCall(widget.targetUserId, status);
      if (!mounted) return;
      await _loadProfile();
    } catch (e) {
      if (mounted) setError(_apiErrorMessage(e));
    } finally {
      if (mounted) setSaving(false);
    }
  }

  Widget _codewordBody(SensitiveProfile p) {
    final can = _canEditSensitiveFields(p);
    final rows = <Widget>[];

    if (p.codewords.isEmpty) {
      rows.add(const _Empty('No codewords set.'));
    } else {
      for (final c in p.codewords) {
        rows.add(
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        c.codewordLabel ?? c.hashPrefix,
                        style: const TextStyle(color: _D.text, fontSize: 13),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        '${c.codewordType ?? '—'} · '
                        '${c.active ? 'active' : 'inactive'}'
                        '${c.triggersMandatoryReporting ? ' · mandatory-report' : ''}'
                        '${c.triggerCount > 0 ? ' · ×${c.triggerCount}' : ''}',
                        style: const TextStyle(color: _D.textDim, fontSize: 11),
                      ),
                    ],
                  ),
                ),
                if (can)
                  IconButton(
                    icon: const Icon(Icons.delete_outline,
                        color: _D.red, size: 20),
                    tooltip: 'Delete codeword',
                    onPressed: () => _confirmDeleteCodeword(c),
                  ),
              ],
            ),
          ),
        );
      }
    }

    if (can) {
      rows.add(
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: _showAddCodewordDialog,
            icon: const Icon(Icons.add, color: _D.gold, size: 18),
            label: const Text('Add Codeword', style: TextStyle(color: _D.gold)),
          ),
        ),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: rows,
    );
  }

  Future<void> _showAddCodewordDialog() async {
    final prof = _profile;
    if (prof == null || !_canEditSensitiveFields(prof)) return;

    final ctrl = TextEditingController();
    try {
      await showDialog<void>(
        context: context,
        barrierDismissible: false,
        builder: (ctx) {
          String cwType = _kCodewordTypesApi.first;
          bool mandatory = false;
          bool submitting = false;
          String? inlineErr;

          return StatefulBuilder(
            builder: (ctx, setDlg) {
              return CallbackShortcuts(
                bindings: <ShortcutActivator, VoidCallback>{
                  const SingleActivator(LogicalKeyboardKey.escape): () {
                    if (!submitting) Navigator.of(ctx).pop();
                  },
                },
                child: Focus(
                  autofocus: true,
                  child: AlertDialog(
                    backgroundColor: _D.bgCard,
                    title: const Text(
                      'Add Codeword',
                      style: TextStyle(color: _D.gold),
                    ),
                    content: SingleChildScrollView(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          TextField(
                            controller: ctrl,
                            enabled: !submitting,
                            style: const TextStyle(color: _D.text),
                            decoration: const InputDecoration(
                              labelText: 'Codeword',
                              hintText:
                                  'Enter codeword — will be hashed before storage',
                              hintStyle: TextStyle(color: _D.textDim),
                              filled: true,
                              fillColor: _D.bgElev,
                              border: OutlineInputBorder(),
                            ),
                          ),
                          const SizedBox(height: 12),
                          DropdownButtonFormField<String>(
                            value: cwType,
                            dropdownColor: _D.bgElev,
                            style: const TextStyle(color: _D.text),
                            decoration: const InputDecoration(
                              labelText: 'Codeword type',
                              filled: true,
                              fillColor: _D.bgElev,
                              border: OutlineInputBorder(),
                              labelStyle: TextStyle(color: _D.textDim),
                            ),
                            items: _kCodewordTypesApi
                                .map(
                                  (e) => DropdownMenuItem(
                                    value: e,
                                    child: Text(e),
                                  ),
                                )
                                .toList(),
                            onChanged: submitting
                                ? null
                                : (v) => setDlg(() {
                                      cwType = v ?? cwType;
                                      if (cwType == 'innocuous_phrase') {
                                        mandatory = false;
                                      }
                                    }),
                          ),
                          const SizedBox(height: 4),
                          CheckboxListTile(
                            value: mandatory,
                            onChanged: (submitting ||
                                    cwType == 'innocuous_phrase')
                                ? null
                                : (v) => setDlg(() => mandatory = v ?? false),
                            title: const Text(
                              'Triggers mandatory reporting',
                              style: TextStyle(color: _D.text, fontSize: 12),
                            ),
                            fillColor:
                                WidgetStateProperty.resolveWith((states) {
                              if (states.contains(WidgetState.selected)) {
                                return _D.gold;
                              }
                              return null;
                            }),
                            checkColor: _D.bgVoid,
                          ),
                          if (inlineErr != null)
                            Padding(
                              padding: const EdgeInsets.only(top: 8),
                              child: Text(
                                inlineErr!,
                                style: const TextStyle(
                                    color: _D.red, fontSize: 11),
                              ),
                            ),
                        ],
                      ),
                    ),
                    actions: [
                      TextButton(
                        onPressed:
                            submitting ? null : () => Navigator.of(ctx).pop(),
                        child: const Text('Cancel'),
                      ),
                      TextButton(
                        onPressed: submitting
                            ? null
                            : () async {
                                final raw = ctrl.text.trim();
                                if (raw.isEmpty) return;
                                if (_blockHarnessNetwork) {
                                  if (ctx.mounted) Navigator.of(ctx).pop();
                                  if (mounted) {
                                    ScaffoldMessenger.of(context).showSnackBar(
                                      const SnackBar(
                                        backgroundColor: _D.bgElev,
                                        content: Text(
                                          'Inspection harness: mutation skipped.',
                                          style: TextStyle(color: _D.gold),
                                        ),
                                      ),
                                    );
                                  }
                                  return;
                                }
                                setDlg(() {
                                  submitting = true;
                                  inlineErr = null;
                                });
                                try {
                                  await _api.postCodeword(
                                    widget.targetUserId,
                                    plaintextCodeword: raw,
                                    codewordType: cwType,
                                    triggersMandatoryReporting:
                                        cwType == 'explicit_word' && mandatory,
                                  );
                                  if (ctx.mounted) Navigator.of(ctx).pop();
                                  await _loadProfile();
                                } catch (e) {
                                  setDlg(() {
                                    submitting = false;
                                    inlineErr = _apiErrorMessage(e);
                                  });
                                }
                              },
                        child: const Text('Add Codeword'),
                      ),
                    ],
                  ),
                ),
              );
            },
          );
        },
      );
    } finally {
      ctrl.dispose();
    }
  }

  Future<void> _confirmDeleteCodeword(Codeword c) async {
    final prof = _profile;
    if (prof == null || !_canEditSensitiveFields(prof)) return;
    final ok = await _confirmDialog(
      title: 'Delete codeword?',
      message: 'Delete codeword? This cannot be undone.',
      confirmLabel: 'Delete',
    );
    if (!ok) return;
    if (_harnessMutationBarrier()) return;
    try {
      await _api.deleteCodeword(widget.targetUserId, c.hashPrefix);
      await _loadProfile();
    } catch (e) {
      _showError(e);
    }
  }

  Widget _triggerDateBody(SensitiveProfile p) {
    final can = _canEditSensitiveFields(p);
    final rows = <Widget>[];

    if (p.triggerDates.isEmpty) {
      rows.add(const _Empty('No trigger dates set.'));
    } else {
      for (final t in p.triggerDates) {
        rows.add(
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        t.triggerDate,
                        style: const TextStyle(color: _D.text, fontSize: 13),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        '${t.dateType ?? '—'} · severity ${t.severity ?? '—'}'
                        '${t.recurringAnnually ? ' · annual' : ''}'
                        '${t.active ? '' : ' · inactive'}',
                        style: const TextStyle(color: _D.textDim, fontSize: 11),
                      ),
                    ],
                  ),
                ),
                if (can) ...[
                  IconButton(
                    icon: const Icon(Icons.edit_outlined,
                        color: _D.cyan, size: 20),
                    tooltip: 'Edit trigger date',
                    onPressed: () => _showTriggerDateDialog(existing: t),
                  ),
                  IconButton(
                    icon: const Icon(Icons.delete_outline,
                        color: _D.red, size: 20),
                    tooltip: 'Delete trigger date',
                    onPressed: () => _confirmDeleteTriggerDate(t),
                  ),
                ],
              ],
            ),
          ),
        );
      }
    }

    if (can) {
      rows.add(
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: () => _showTriggerDateDialog(),
            icon: const Icon(Icons.add, color: _D.gold, size: 18),
            label: const Text(
              'Add Trigger Date',
              style: TextStyle(color: _D.gold),
            ),
          ),
        ),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: rows,
    );
  }

  Future<void> _confirmDeleteTriggerDate(TriggerDate t) async {
    final prof = _profile;
    if (prof == null || !_canEditSensitiveFields(prof)) return;
    final ok = await _confirmDialog(
      title: 'Delete trigger date?',
      message: 'Remove this trigger date entry? This cannot be undone.',
      confirmLabel: 'Delete',
    );
    if (!ok) return;
    if (_harnessMutationBarrier()) return;
    try {
      await _api.deleteTriggerDate(widget.targetUserId, t.id);
      await _loadProfile();
    } catch (e) {
      _showError(e);
    }
  }

  Future<void> _showTriggerDateDialog({TriggerDate? existing}) async {
    final prof = _profile;
    if (prof == null || !_canEditSensitiveFields(prof)) return;

    final notesCtrl = TextEditingController(
      text: existing?.notesRedacted ?? '',
    );
    try {
      await showDialog<void>(
        context: context,
        barrierDismissible: false,
        builder: (ctx) {
          final now = DateTime.now();
          final firstCal = DateTime(now.year - 50, now.month, now.day);
          final lastCal = DateTime(now.year + 10, now.month, now.day);
          DateTime selectedDay = existing != null
              ? (DateTime.tryParse(existing.triggerDate) != null
                  ? DateTime(
                      DateTime.parse(existing.triggerDate).year,
                      DateTime.parse(existing.triggerDate).month,
                      DateTime.parse(existing.triggerDate).day,
                    )
                  : firstCal)
              : now;
          if (selectedDay.isBefore(firstCal)) selectedDay = firstCal;
          if (selectedDay.isAfter(lastCal)) selectedDay = lastCal;

          String dateType = existing?.dateType ?? _kTriggerDateTypes.first;
          if (!_kTriggerDateTypes.contains(dateType)) {
            dateType = _kTriggerDateTypes.first;
          }
          String severity = existing?.severity ?? 'high';
          if (!_kSeverities.contains(severity)) severity = 'high';
          bool recurring = existing?.recurringAnnually ?? true;
          bool submitting = false;
          String? inlineErr;

          Future<void> pickDate(StateSetter setDlg) async {
            final picked = await showDatePicker(
              context: ctx,
              initialDate: selectedDay,
              firstDate: firstCal,
              lastDate: lastCal,
              builder: (c, child) => Theme(
                data: Theme.of(c).copyWith(
                  colorScheme: const ColorScheme.dark(
                    primary: _D.gold,
                    surface: _D.bgElev,
                  ),
                ),
                child: child ?? const SizedBox.shrink(),
              ),
            );
            if (picked != null) {
              setDlg(() => selectedDay = picked);
            }
          }

          return StatefulBuilder(
            builder: (ctx, setDlg) {
              return CallbackShortcuts(
                bindings: <ShortcutActivator, VoidCallback>{
                  const SingleActivator(LogicalKeyboardKey.escape): () {
                    if (!submitting) Navigator.of(ctx).pop();
                  },
                },
                child: Focus(
                  autofocus: true,
                  child: AlertDialog(
                    backgroundColor: _D.bgCard,
                    title: Text(
                      existing == null
                          ? 'Add Trigger Date'
                          : 'Edit Trigger Date',
                      style: const TextStyle(color: _D.gold),
                    ),
                    content: SingleChildScrollView(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          ListTile(
                            title: const Text(
                              'Trigger date',
                              style: TextStyle(color: _D.textDim, fontSize: 12),
                            ),
                            subtitle: Text(
                              _dateOnlyIso(selectedDay),
                              style: const TextStyle(color: _D.gold),
                            ),
                            trailing: TextButton(
                              onPressed:
                                  submitting ? null : () => pickDate(setDlg),
                              child: const Text('Pick'),
                            ),
                          ),
                          DropdownButtonFormField<String>(
                            value: dateType,
                            dropdownColor: _D.bgElev,
                            style: const TextStyle(color: _D.text),
                            decoration: const InputDecoration(
                              labelText: 'Date type',
                              filled: true,
                              fillColor: _D.bgElev,
                              border: OutlineInputBorder(),
                            ),
                            items: _kTriggerDateTypes
                                .map((e) => DropdownMenuItem(
                                      value: e,
                                      child: Text(e),
                                    ))
                                .toList(),
                            onChanged: submitting
                                ? null
                                : (v) => setDlg(() => dateType = v ?? dateType),
                          ),
                          const SizedBox(height: 10),
                          DropdownButtonFormField<String>(
                            value: severity,
                            dropdownColor: _D.bgElev,
                            style: const TextStyle(color: _D.text),
                            decoration: const InputDecoration(
                              labelText: 'Severity',
                              filled: true,
                              fillColor: _D.bgElev,
                              border: OutlineInputBorder(),
                            ),
                            items: _kSeverities
                                .map((e) => DropdownMenuItem(
                                      value: e,
                                      child: Text(e),
                                    ))
                                .toList(),
                            onChanged: submitting
                                ? null
                                : (v) => setDlg(() => severity = v ?? severity),
                          ),
                          const SizedBox(height: 8),
                          CheckboxListTile(
                            value: recurring,
                            onChanged: submitting
                                ? null
                                : (v) => setDlg(() => recurring = v ?? false),
                            title: const Text(
                              'Recurring annually',
                              style: TextStyle(color: _D.text, fontSize: 12),
                            ),
                            fillColor:
                                WidgetStateProperty.resolveWith((states) {
                              if (states.contains(WidgetState.selected)) {
                                return _D.gold;
                              }
                              return null;
                            }),
                            checkColor: _D.bgVoid,
                          ),
                          TextField(
                            controller: notesCtrl,
                            enabled: !submitting,
                            maxLength: 500,
                            maxLines: 3,
                            style: const TextStyle(color: _D.text),
                            decoration: const InputDecoration(
                              labelText: 'Notes (redacted)',
                              helperText: 'No PII — server screens this field; '
                                  'do not include names, dates of birth, addresses',
                              helperMaxLines: 3,
                              filled: true,
                              fillColor: _D.bgElev,
                              border: OutlineInputBorder(),
                              labelStyle: TextStyle(color: _D.textDim),
                            ),
                          ),
                          if (inlineErr != null)
                            Padding(
                              padding: const EdgeInsets.only(top: 8),
                              child: Text(
                                inlineErr!,
                                style: const TextStyle(
                                    color: _D.red, fontSize: 11),
                              ),
                            ),
                        ],
                      ),
                    ),
                    actions: [
                      TextButton(
                        onPressed:
                            submitting ? null : () => Navigator.of(ctx).pop(),
                        child: const Text('Cancel'),
                      ),
                      TextButton(
                        onPressed: submitting
                            ? null
                            : () async {
                                if (_blockHarnessNetwork) {
                                  if (ctx.mounted) Navigator.of(ctx).pop();
                                  _harnessMutationBarrier();
                                  return;
                                }
                                setDlg(() {
                                  submitting = true;
                                  inlineErr = null;
                                });
                                final iso = _dateOnlyIso(selectedDay);
                                final notesTrim = notesCtrl.text.trim();
                                final oldId = existing?.id;
                                try {
                                  await _api.postTriggerDate(
                                    widget.targetUserId,
                                    triggerDateIso: iso,
                                    dateType: dateType,
                                    severity: severity,
                                    recurringAnnually: recurring,
                                    notesRedacted:
                                        notesTrim.isEmpty ? null : notesTrim,
                                  );
                                  if (oldId != null) {
                                    await _api.deleteTriggerDate(
                                      widget.targetUserId,
                                      oldId,
                                    );
                                  }
                                  if (ctx.mounted) Navigator.of(ctx).pop();
                                  await _loadProfile();
                                } catch (e) {
                                  setDlg(() {
                                    submitting = false;
                                    inlineErr = _apiErrorMessage(e);
                                  });
                                }
                              },
                        child: Text(existing == null ? 'Add' : 'Save'),
                      ),
                    ],
                  ),
                ),
              );
            },
          );
        },
      );
    } finally {
      notesCtrl.dispose();
    }
  }

  Widget _polyvictimBody(SensitiveProfile p) {
    final can = _canEditSensitiveFields(p);
    final rows = <Widget>[];

    if (p.polyvictimLayers.isEmpty) {
      rows.add(const _Empty('No polyvictim layers recorded.'));
    } else {
      for (final l in p.polyvictimLayers) {
        final pending = _isPendingPolySuggestion(l);
        rows.add(
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Text(
                            l.layerType,
                            style:
                                const TextStyle(color: _D.text, fontSize: 13),
                          ),
                          if (pending) ...[
                            const SizedBox(width: 6),
                            Container(
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 6, vertical: 1),
                              decoration: BoxDecoration(
                                color: _D.gold.withOpacity(0.15),
                                borderRadius: BorderRadius.circular(4),
                                border: Border.all(
                                    color: _D.gold.withOpacity(0.5)),
                              ),
                              child: const Text(
                                'SYSTEM SUGGESTED · PENDING REVIEW',
                                style: TextStyle(
                                  color: _D.gold,
                                  fontSize: 9,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ),
                          ],
                        ],
                      ),
                      const SizedBox(height: 2),
                      Text(
                        'severity ${l.severity}'
                        '${l.active ? '' : ' · inactive'}',
                        style: const TextStyle(color: _D.textDim, fontSize: 11),
                      ),
                      if (l.notesRedacted != null &&
                          l.notesRedacted!.isNotEmpty) ...[
                        const SizedBox(height: 4),
                        Text(
                          l.notesRedacted!,
                          style: const TextStyle(
                              color: _D.textDim,
                              fontSize: 11,
                              fontStyle: FontStyle.italic),
                        ),
                      ],
                    ],
                  ),
                ),
                if (can && pending) ...[
                  IconButton(
                    icon: const Icon(Icons.check_circle_outline,
                        color: _D.gold, size: 20),
                    tooltip: 'Confirm & activate',
                    onPressed: () => _confirmActivatePolyLayer(l),
                  ),
                  IconButton(
                    icon: const Icon(Icons.close, color: _D.red, size: 20),
                    tooltip: 'Dismiss suggestion',
                    onPressed: () => _confirmDismissPolySuggestion(l),
                  ),
                ] else if (can)
                  IconButton(
                    icon: const Icon(Icons.delete_outline,
                        color: _D.red, size: 20),
                    tooltip: 'Remove layer',
                    onPressed: () => _confirmDeletePolyLayer(l),
                  ),
              ],
            ),
          ),
        );
      }
    }

    if (can) {
      rows.add(
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: _showAddPolyLayerDialog,
            icon: const Icon(Icons.add, color: _D.gold, size: 18),
            label: const Text(
              'Add Layer',
              style: TextStyle(color: _D.gold),
            ),
          ),
        ),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: rows,
    );
  }

  Future<void> _confirmDeletePolyLayer(PolyvictimLayer l) async {
    final prof = _profile;
    if (prof == null || !_canEditSensitiveFields(prof)) return;
    final ok = await _confirmDialog(
      title: 'Delete polyvictim layer?',
      message: 'Remove this layer record? This cannot be undone.',
      confirmLabel: 'Delete',
    );
    if (!ok) return;
    if (_harnessMutationBarrier()) return;
    try {
      await _api.deletePolyvictimLayer(widget.targetUserId, l.id);
      await _loadProfile();
    } catch (e) {
      _showError(e);
    }
  }

  /// True when this row was inserted automatically from a disclosure
  /// (see `sensitive_clinical_bridge._suggest_polyvictim_layer`) and has not
  /// yet been reviewed by a clinician.
  bool _isPendingPolySuggestion(PolyvictimLayer l) =>
      !l.active && l.setByClinicianId == 'system_auto_suggested_pending_review';

  Future<void> _confirmActivatePolyLayer(PolyvictimLayer l) async {
    final prof = _profile;
    if (prof == null || !_canEditSensitiveFields(prof)) return;
    final ok = await _confirmDialog(
      title: 'Confirm this layer?',
      message: 'This will activate the layer as clinically applicable and '
          'attribute it to you for the record.',
      confirmLabel: 'Confirm & Activate',
    );
    if (!ok) return;
    if (_harnessMutationBarrier()) return;
    try {
      await _api.activatePolyvictimLayer(widget.targetUserId, l.id);
      await _loadProfile();
    } catch (e) {
      _showError(e);
    }
  }

  Future<void> _confirmDismissPolySuggestion(PolyvictimLayer l) async {
    final prof = _profile;
    if (prof == null || !_canEditSensitiveFields(prof)) return;
    final ok = await _confirmDialog(
      title: 'Dismiss suggestion?',
      message: 'This system-suggested layer will be removed. Use this if '
          'it does not reflect this client\'s clinical picture.',
      confirmLabel: 'Dismiss',
    );
    if (!ok) return;
    if (_harnessMutationBarrier()) return;
    try {
      await _api.dismissPolyvictimLayerSuggestion(widget.targetUserId, l.id);
      await _loadProfile();
    } catch (e) {
      _showError(e);
    }
  }

  Future<void> _showAddPolyLayerDialog() async {
    final prof = _profile;
    if (prof == null || !_canEditSensitiveFields(prof)) return;

    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) {
        String layerType = _kPolyvictimLayerTypes.first;
        String severity = 'high';
        bool submitting = false;
        String? inlineErr;

        return StatefulBuilder(
          builder: (ctx, setDlg) {
            return CallbackShortcuts(
              bindings: <ShortcutActivator, VoidCallback>{
                const SingleActivator(LogicalKeyboardKey.escape): () {
                  if (!submitting) Navigator.of(ctx).pop();
                },
              },
              child: Focus(
                autofocus: true,
                child: AlertDialog(
                  backgroundColor: _D.bgCard,
                  title: const Text(
                    'Add Polyvictim Layer',
                    style: TextStyle(color: _D.gold),
                  ),
                  content: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      DropdownButtonFormField<String>(
                        value: layerType,
                        dropdownColor: _D.bgElev,
                        style: const TextStyle(color: _D.text),
                        decoration: const InputDecoration(
                          labelText: 'Layer type',
                          filled: true,
                          fillColor: _D.bgElev,
                          border: OutlineInputBorder(),
                        ),
                        items: _kPolyvictimLayerTypes
                            .map((e) => DropdownMenuItem(
                                  value: e,
                                  child: Text(e),
                                ))
                            .toList(),
                        onChanged: submitting
                            ? null
                            : (v) => setDlg(() => layerType = v ?? layerType),
                      ),
                      const SizedBox(height: 10),
                      DropdownButtonFormField<String>(
                        value: severity,
                        dropdownColor: _D.bgElev,
                        style: const TextStyle(color: _D.text),
                        decoration: const InputDecoration(
                          labelText: 'Severity',
                          filled: true,
                          fillColor: _D.bgElev,
                          border: OutlineInputBorder(),
                        ),
                        items: _kSeverities
                            .map((e) => DropdownMenuItem(
                                  value: e,
                                  child: Text(e),
                                ))
                            .toList(),
                        onChanged: submitting
                            ? null
                            : (v) => setDlg(() => severity = v ?? severity),
                      ),
                      if (inlineErr != null)
                        Padding(
                          padding: const EdgeInsets.only(top: 8),
                          child: Text(
                            inlineErr!,
                            style: const TextStyle(color: _D.red, fontSize: 11),
                          ),
                        ),
                    ],
                  ),
                  actions: [
                    TextButton(
                      onPressed:
                          submitting ? null : () => Navigator.of(ctx).pop(),
                      child: const Text('Cancel'),
                    ),
                    TextButton(
                      onPressed: submitting
                          ? null
                          : () async {
                              if (_blockHarnessNetwork) {
                                Navigator.of(ctx).pop();
                                _harnessMutationBarrier();
                                return;
                              }
                              setDlg(() {
                                submitting = true;
                                inlineErr = null;
                              });
                              try {
                                await _api.postPolyvictimLayer(
                                  widget.targetUserId,
                                  layerType: layerType,
                                  severity: severity,
                                );
                                if (ctx.mounted) Navigator.of(ctx).pop();
                                await _loadProfile();
                              } catch (e) {
                                setDlg(() {
                                  submitting = false;
                                  inlineErr = _apiErrorMessage(e);
                                });
                              }
                            },
                      child: const Text('Add'),
                    ),
                  ],
                ),
              ),
            );
          },
        );
      },
    );
  }

  Widget _legalBody(SensitiveProfile p) {
    final can = _canEditSensitiveFields(p);
    final rows = <Widget>[];

    if (p.legalStatus.isEmpty) {
      rows.add(const _Empty('No legal cases on file.'));
    } else {
      for (final c in p.legalStatus) {
        rows.add(
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${c.caseType} · ${c.caseStatus}',
                        style: const TextStyle(color: _D.text, fontSize: 13),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        c.nextEventDate != null
                            ? 'next event: ${c.nextEventDate}'
                            : 'no scheduled event',
                        style: const TextStyle(color: _D.textDim, fontSize: 11),
                      ),
                      if (c.attorneyContactRedacted != null &&
                          c.attorneyContactRedacted!.isNotEmpty)
                        Text(
                          'counsel: ${c.attorneyContactRedacted}',
                          style:
                              const TextStyle(color: _D.textDim, fontSize: 11),
                        ),
                    ],
                  ),
                ),
                if (can)
                  IconButton(
                    icon: const Icon(Icons.edit_outlined,
                        color: _D.cyan, size: 20),
                    tooltip: 'Edit case',
                    onPressed: () => _showLegalCaseDialog(existing: c),
                  ),
              ],
            ),
          ),
        );
      }
    }

    if (can) {
      rows.add(
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: () => _showLegalCaseDialog(),
            icon: const Icon(Icons.add, color: _D.gold, size: 18),
            label: const Text(
              'Add Case',
              style: TextStyle(color: _D.gold),
            ),
          ),
        ),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: rows,
    );
  }

  Future<void> _showLegalCaseDialog({LegalCase? existing}) async {
    final prof = _profile;
    if (prof == null || !_canEditSensitiveFields(prof)) return;

    final attorneyCtrl = TextEditingController(
      text: existing?.attorneyContactRedacted ?? '',
    );
    try {
      await showDialog<void>(
        context: context,
        barrierDismissible: false,
        builder: (ctx) {
          final now = DateTime.now();
          final firstFuture = DateTime(now.year, now.month, now.day);
          final lastFuture = DateTime(now.year + 15, now.month, now.day);

          String caseType = existing?.caseType ?? _kLegalCaseTypes.first;
          if (!_kLegalCaseTypes.contains(caseType)) {
            caseType = _kLegalCaseTypes.first;
          }
          String caseStatus = existing?.caseStatus ?? _kLegalCaseStatuses.first;
          if (!_kLegalCaseStatuses.contains(caseStatus)) {
            caseStatus = _kLegalCaseStatuses.first;
          }

          DateTime? nextEvt;
          if (existing?.nextEventDate != null) {
            nextEvt = DateTime.tryParse(existing!.nextEventDate!);
            if (nextEvt != null) {
              nextEvt = DateTime(nextEvt.year, nextEvt.month, nextEvt.day);
            }
          }

          bool submitting = false;
          String? inlineErr;

          Future<void> pickLegalDate(StateSetter setDlg) async {
            final picked = await showDatePicker(
              context: ctx,
              initialDate: nextEvt ?? firstFuture,
              firstDate: firstFuture,
              lastDate: lastFuture,
              builder: (c, child) => Theme(
                data: Theme.of(c).copyWith(
                  colorScheme: const ColorScheme.dark(
                    primary: _D.gold,
                    surface: _D.bgElev,
                  ),
                ),
                child: child ?? const SizedBox.shrink(),
              ),
            );
            if (picked != null) {
              setDlg(() => nextEvt = picked);
            }
          }

          return StatefulBuilder(
            builder: (ctx, setDlg) {
              return CallbackShortcuts(
                bindings: <ShortcutActivator, VoidCallback>{
                  const SingleActivator(LogicalKeyboardKey.escape): () {
                    if (!submitting) Navigator.of(ctx).pop();
                  },
                },
                child: Focus(
                  autofocus: true,
                  child: AlertDialog(
                    backgroundColor: _D.bgCard,
                    title: Text(
                      existing == null ? 'Add Case' : 'Edit Case',
                      style: const TextStyle(color: _D.gold),
                    ),
                    content: SingleChildScrollView(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          if (existing != null)
                            Text(
                              'Case type (read-only): ${existing.caseType}',
                              style: const TextStyle(
                                  color: _D.textDim, fontSize: 12),
                            ),
                          if (existing == null) ...[
                            DropdownButtonFormField<String>(
                              value: caseType,
                              dropdownColor: _D.bgElev,
                              style: const TextStyle(color: _D.text),
                              decoration: const InputDecoration(
                                labelText: 'Case type',
                                filled: true,
                                fillColor: _D.bgElev,
                                border: OutlineInputBorder(),
                              ),
                              items: _kLegalCaseTypes
                                  .map((e) => DropdownMenuItem(
                                        value: e,
                                        child: Text(e),
                                      ))
                                  .toList(),
                              onChanged: submitting
                                  ? null
                                  : (v) =>
                                      setDlg(() => caseType = v ?? caseType),
                            ),
                          ],
                          const SizedBox(height: 10),
                          DropdownButtonFormField<String>(
                            value: caseStatus,
                            dropdownColor: _D.bgElev,
                            style: const TextStyle(color: _D.text),
                            decoration: const InputDecoration(
                              labelText: 'Case status',
                              filled: true,
                              fillColor: _D.bgElev,
                              border: OutlineInputBorder(),
                            ),
                            items: _kLegalCaseStatuses
                                .map((e) => DropdownMenuItem(
                                      value: e,
                                      child: Text(e),
                                    ))
                                .toList(),
                            onChanged: submitting
                                ? null
                                : (v) =>
                                    setDlg(() => caseStatus = v ?? caseStatus),
                          ),
                          const SizedBox(height: 8),
                          ListTile(
                            title: const Text(
                              'Next event date (optional)',
                              style: TextStyle(color: _D.textDim, fontSize: 12),
                            ),
                            subtitle: Text(
                              nextEvt != null ? _dateOnlyIso(nextEvt!) : 'none',
                              style: const TextStyle(color: _D.gold),
                            ),
                            trailing: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                if (nextEvt != null)
                                  TextButton(
                                    onPressed: submitting
                                        ? null
                                        : () => setDlg(() => nextEvt = null),
                                    child: const Text('Clear'),
                                  ),
                                TextButton(
                                  onPressed: submitting
                                      ? null
                                      : () => pickLegalDate(setDlg),
                                  child: const Text('Pick'),
                                ),
                              ],
                            ),
                          ),
                          TextField(
                            controller: attorneyCtrl,
                            enabled: !submitting,
                            maxLength: 200,
                            style: const TextStyle(color: _D.text),
                            decoration: const InputDecoration(
                              labelText: 'Attorney / org (redacted)',
                              helperText:
                                  'Name or organization only — no PII per Gap C',
                              filled: true,
                              fillColor: _D.bgElev,
                              border: OutlineInputBorder(),
                            ),
                          ),
                          if (inlineErr != null)
                            Padding(
                              padding: const EdgeInsets.only(top: 8),
                              child: Text(
                                inlineErr!,
                                style: const TextStyle(
                                    color: _D.red, fontSize: 11),
                              ),
                            ),
                        ],
                      ),
                    ),
                    actions: [
                      TextButton(
                        onPressed:
                            submitting ? null : () => Navigator.of(ctx).pop(),
                        child: const Text('Cancel'),
                      ),
                      TextButton(
                        onPressed: submitting
                            ? null
                            : () async {
                                if (_blockHarnessNetwork) {
                                  Navigator.of(ctx).pop();
                                  _harnessMutationBarrier();
                                  return;
                                }
                                setDlg(() {
                                  submitting = true;
                                  inlineErr = null;
                                });
                                final nextIso = nextEvt != null
                                    ? _dateOnlyIso(nextEvt!)
                                    : null;
                                final att = attorneyCtrl.text.trim();
                                try {
                                  if (existing == null) {
                                    await _api.postLegalStatus(
                                      widget.targetUserId,
                                      caseType: caseType,
                                      caseStatus: caseStatus,
                                      nextEventDateIso: nextIso,
                                      attorneyContactRedacted:
                                          att.isEmpty ? null : att,
                                    );
                                  } else {
                                    await _api.patchLegalStatus(
                                      widget.targetUserId,
                                      existing.id,
                                      caseStatus: caseStatus,
                                      nextEventDateIso: nextIso,
                                      attorneyContactRedacted: att,
                                    );
                                  }
                                  if (ctx.mounted) Navigator.of(ctx).pop();
                                  await _loadProfile();
                                } catch (e) {
                                  setDlg(() {
                                    submitting = false;
                                    inlineErr = _apiErrorMessage(e);
                                  });
                                }
                              },
                        child: Text(existing == null ? 'Add' : 'Save'),
                      ),
                    ],
                  ),
                ),
              );
            },
          );
        },
      );
    } finally {
      attorneyCtrl.dispose();
    }
  }

  Widget _safeSilenceBody(SensitiveProfile p) {
    final s = p.safeSilence;
    return _SafeSilencePanel(
      state: s,
      isAdmin: _isAdmin,
      principalUsername: _currentPrincipalUsername,
      hasActiveCodeword: p.activeCodewordCount > 0,
      onPropose: _onProposeSafeSilence,
      onApprove: _onApproveSafeSilence,
      onCancelPending: _onCoachCancelSafeSilenceProposal,
      onRejectPending: _onAdminRejectSafeSilenceProposal,
      onRevokeActive: _onAdminRevokeSafeSilenceActive,
    );
  }

  Future<void> _deleteSafeSilenceMutation(String successMsg) async {
    if (_harnessMutationBarrier()) return;
    try {
      await _api.deleteSafeSilence(widget.targetUserId);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          backgroundColor: _D.bgElev,
          content: Text(successMsg, style: const TextStyle(color: _D.gold)),
        ),
      );
      _loadProfile();
    } catch (e) {
      _showError(e);
    }
  }

  Future<void> _onCoachCancelSafeSilenceProposal() async {
    final ok = await _confirmDialog(
      title: 'Cancel proposal?',
      message: 'Withdraw this Safe Silence proposal?',
      confirmLabel: 'Cancel proposal',
    );
    if (!ok) return;
    await _deleteSafeSilenceMutation('Safe Silence proposal cancelled.');
  }

  Future<void> _onAdminRejectSafeSilenceProposal() async {
    final ok = await _confirmDialog(
      title: 'Reject proposal?',
      message: 'Reject this Safe Silence proposal?',
      confirmLabel: 'Reject',
    );
    if (!ok) return;
    await _deleteSafeSilenceMutation('Safe Silence proposal rejected.');
  }

  Future<void> _onAdminRevokeSafeSilenceActive() async {
    final ok = await _confirmDialog(
      title: 'Revoke Silence Mode?',
      message: 'Revoking will resume 72-hour check-in cadence immediately. '
          'Confirm only if survivor\'s safety net should be restored now.',
      confirmLabel: 'Revoke',
    );
    if (!ok) return;
    await _deleteSafeSilenceMutation('Safe Silence revoked.');
  }

  Future<void> _onProposeSafeSilence(String reason) async {
    if (_harnessMutationBarrier()) return;
    try {
      final out = await _api.proposeSafeSilence(
        widget.targetUserId,
        reasonRedacted: reason,
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          backgroundColor: _D.bgElev,
          content: Text(
            'Proposed (id: ${out['proposal_id']}). '
            'A separate admin session must approve within 7 days.',
            style: const TextStyle(color: _D.gold),
          ),
        ),
      );
      _loadProfile();
    } catch (e) {
      _showError(e);
    }
  }

  Future<void> _onApproveSafeSilence(String proposalId, String? note) async {
    if (_harnessMutationBarrier()) return;
    try {
      await _api.approveSafeSilence(
        widget.targetUserId,
        proposalId: proposalId,
        approverNoteRedacted: note,
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          backgroundColor: _D.bgElev,
          content: Text(
            'Safe Silence approved. Active for 30 days.',
            style: TextStyle(color: _D.cyan),
          ),
        ),
      );
      _loadProfile();
    } catch (e) {
      _showError(e);
    }
  }

  void _showError(Object e) {
    if (!mounted) return;
    final base = _apiErrorMessage(e);
    String hint = base;
    // Surface the structured 409s as inline-friendly text.
    if (hint.contains('same_session_violation')) {
      hint =
          'Same-session block: a different user must approve in a separate session.';
    } else if (hint.contains('requires_codeword')) {
      hint =
          'At least one active codeword must be set before approval can succeed.';
    } else if (hint.contains('stale_proposal') ||
        hint.contains('proposal_id')) {
      hint =
          'Proposal is stale or rotated. Ask the coach to re-propose, then approve the new id.';
    }
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        backgroundColor: _D.red,
        duration: const Duration(seconds: 5),
        content: Text(hint, style: const TextStyle(color: Colors.white)),
      ),
    );
  }

  Widget _activityLogBody() {
    return _ActivityLogPanel(
      events: _logEvents,
      loading: _logLoading,
      error: _logError,
      days: _logDays,
      exhausted: _logExhausted,
      onChangeDays: (d) {
        setState(() => _logDays = d);
        _loadActivityLog(reset: true);
      },
      onLoadOlder: () => _loadActivityLog(reset: false),
    );
  }

  // ---------------------------------------------------------------------------
  // PATH-C: COACH-INITIATED SELF-ENROLLMENT
  //
  // Opens the enrollment dialog. The dialog is a self-contained modal that
  // collects (cohort_label, population_type, informed_consent_confirmed) and
  // POSTs to /api/coach/sensitive-profile/{id}/enroll. On success we close
  // the dialog, clear the not-enrolled banner via _loadProfile(), and show
  // a snackbar. On failure we map the server `reason` codes to the four
  // UX outcomes the spec calls out (consent_required snackbar,
  // requires_guardian_consent modal, already_enrolled refresh modal, generic
  // failure snackbar).
  // ---------------------------------------------------------------------------
  Future<void> _openEnrollmentDialog() async {
    if (_enrollInFlight) return;
    final result = await showDialog<_EnrollmentDialogResult>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => _EnrollmentDialog(targetUserId: widget.targetUserId),
    );
    if (result == null || !mounted) return;
    await _submitEnrollment(result);
  }

  Future<void> _submitEnrollment(_EnrollmentDialogResult r) async {
    setState(() => _enrollInFlight = true);
    try {
      await _api.enrollClient(
        widget.targetUserId,
        cohortLabel: r.cohortLabel,
        populationType: r.populationType,
        informedConsentConfirmed: r.informedConsentConfirmed,
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          backgroundColor: _D.bgElev,
          content: Text(
            'Client enrolled in cohort: ${r.cohortLabel}',
            style: const TextStyle(color: _D.cyan),
          ),
        ),
      );
      await _loadProfile();
    } on _ApiError catch (err) {
      if (!mounted) return;
      await _handleEnrollmentFailure(err);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          backgroundColor: _D.red,
          content: Text(
            'Enrollment failed. Please try again or contact admin.',
            style: TextStyle(color: Colors.white),
          ),
        ),
      );
    } finally {
      if (mounted) setState(() => _enrollInFlight = false);
    }
  }

  Future<void> _handleEnrollmentFailure(_ApiError err) async {
    final reason = err.reason.toLowerCase();
    if (reason.contains('consent_required')) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          backgroundColor: _D.yellow,
          content: Text(
            'Please confirm informed consent to enroll.',
            style: TextStyle(color: Colors.black),
          ),
        ),
      );
      // Re-open dialog with checkbox unchecked (default state).
      final retry = await showDialog<_EnrollmentDialogResult>(
        context: context,
        barrierDismissible: false,
        builder: (ctx) => _EnrollmentDialog(targetUserId: widget.targetUserId),
      );
      if (retry != null && mounted) {
        await _submitEnrollment(retry);
      }
      return;
    }
    if (reason.contains('requires_guardian_consent')) {
      await showDialog<void>(
        context: context,
        builder: (ctx) => AlertDialog(
          backgroundColor: _D.bgCard,
          title: const Text(
            'Guardian Consent Required',
            style: TextStyle(color: _D.gold),
          ),
          content: const Text(
            'Minor enrollment requires guardian dual-approval. This client '
            'has not completed the guardian consent flow. Contact admin to '
            'initiate guardian consent.',
            style: TextStyle(color: _D.text),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(),
              child: const Text('OK', style: TextStyle(color: _D.gold)),
            ),
          ],
        ),
      );
      return;
    }
    if (reason.contains('already_enrolled')) {
      await showDialog<void>(
        context: context,
        builder: (ctx) => AlertDialog(
          backgroundColor: _D.bgCard,
          title: const Text(
            'Already Enrolled',
            style: TextStyle(color: _D.gold),
          ),
          content: const Text(
            'This client is already enrolled. Refresh the screen to load '
            'their profile.',
            style: TextStyle(color: _D.text),
          ),
          actions: [
            TextButton(
              onPressed: () {
                Navigator.of(ctx).pop();
                _loadProfile();
              },
              child: const Text('Refresh', style: TextStyle(color: _D.cyan)),
            ),
          ],
        ),
      );
      return;
    }
    if (reason.contains('not_found')) {
      // Coach not authorized — server hides the feature behind a 404. We
      // surface a neutral message and refuse to show the dialog again.
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          backgroundColor: _D.red,
          content: Text(
            'Enrollment is not available for this account.',
            style: TextStyle(color: Colors.white),
          ),
        ),
      );
      return;
    }
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        backgroundColor: _D.red,
        content: Text(
          'Enrollment failed: ${err.reason}',
          style: const TextStyle(color: Colors.white),
        ),
      ),
    );
  }
}

// =============================================================================
// SHARED WIDGETS
// =============================================================================

class _PopulationTypeBanner extends StatelessWidget {
  const _PopulationTypeBanner();

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: _D.bgCard,
        border: Border.all(color: _D.yellow.withValues(alpha: 0.5)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: const Row(
        children: [
          Icon(Icons.info_outline, color: _D.yellow, size: 18),
          SizedBox(width: 10),
          Expanded(
            child: Text(
              'Set population type to see calibrated preset. '
              'Defaulting to general_trauma.',
              style: TextStyle(color: _D.text, fontSize: 12),
            ),
          ),
        ],
      ),
    );
  }
}

// =============================================================================
// PATH-C: NOT-ENROLLED BANNER + ENROLLMENT DIALOG (M215 + M216)
//
// _NotEnrolledBanner shows the "client not enrolled" message and, when the
// current coach has coach_sensitive_bridge_authorized=TRUE, also surfaces an
// "Enroll this client" pill button. Unauthorized coaches see only the
// message — there is no way to discover the enrollment surface from the UI.
//
// _EnrollmentDialog gathers (cohort_label, population_type,
// informed_consent_confirmed) and pops a _EnrollmentDialogResult. The
// "Enroll Client" submit button is disabled until informed_consent is
// checked AND a population_type is selected.
// =============================================================================
class _NotEnrolledBanner extends StatelessWidget {
  final bool coachAuthorized;
  final bool enrollInFlight;
  final VoidCallback onEnrollPressed;

  const _NotEnrolledBanner({
    required this.coachAuthorized,
    required this.enrollInFlight,
    required this.onEnrollPressed,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
      decoration: BoxDecoration(
        color: _D.bgCard,
        border: Border.all(color: _D.cyan.withValues(alpha: 0.5)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.shield_outlined, color: _D.cyan, size: 18),
              SizedBox(width: 10),
              Expanded(
                child: Text(
                  'This client is not enrolled in the Sensitive Clinical '
                  'Bridge. Contact admin to enroll.',
                  style: TextStyle(color: _D.text, fontSize: 12),
                ),
              ),
            ],
          ),
          if (coachAuthorized) ...[
            const SizedBox(height: 12),
            Align(
              alignment: Alignment.centerLeft,
              child: ElevatedButton.icon(
                onPressed: enrollInFlight ? null : onEnrollPressed,
                icon: const Icon(Icons.add_moderator_outlined,
                    color: Colors.black, size: 16),
                label: Text(
                  enrollInFlight ? 'Enrolling…' : 'Enroll this client',
                  style: const TextStyle(
                    color: Colors.black,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                style: ElevatedButton.styleFrom(
                  backgroundColor: _D.cyan,
                  disabledBackgroundColor: _D.cyan.withValues(alpha: 0.4),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(20),
                  ),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 16,
                    vertical: 8,
                  ),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _EnrollmentDialogResult {
  final String cohortLabel;
  final String populationType;
  final bool informedConsentConfirmed;
  const _EnrollmentDialogResult({
    required this.cohortLabel,
    required this.populationType,
    required this.informedConsentConfirmed,
  });
}

class _EnrollmentDialog extends StatefulWidget {
  final String targetUserId;
  const _EnrollmentDialog({required this.targetUserId});

  @override
  State<_EnrollmentDialog> createState() => _EnrollmentDialogState();
}

class _EnrollmentDialogState extends State<_EnrollmentDialog> {
  // Cohort enum mirrors VALID_COACH_ENROLLMENT_COHORTS in
  // sensitive_profile_api.py. Keep in sync if the backend list changes.
  static const _cohortOptions = [
    'inspection_test',
    'pilot_5',
    'cohort_25',
    'cohort_100',
    'general_availability',
  ];
  static const _populationOptions = [
    'adult_survivor',
    'minor_survivor',
    'transitioning_youth_16_to_21',
  ];

  String _cohort = 'inspection_test';
  String? _population; // intentionally null — coach must choose
  bool _consent = false;

  bool get _canSubmit => _consent && _population != null;

  String _cohortTooltip(String cohort) {
    if (cohort == 'inspection_test') {
      return 'Initial screen evaluation. Does not engage shadow-mode telemetry.';
    }
    return 'Requires informed consent on file. inspection_test is appropriate '
        'for initial screen evaluation without engaging shadow-mode telemetry.';
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: _D.bgCard,
      title: Text(
        'Enroll ${widget.targetUserId}',
        style: const TextStyle(color: _D.gold),
      ),
      content: SizedBox(
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Cohort label',
              style: TextStyle(color: _D.textDim, fontSize: 11),
            ),
            const SizedBox(height: 4),
            DropdownButtonFormField<String>(
              initialValue: _cohort,
              dropdownColor: _D.bgElev,
              style: const TextStyle(color: _D.text, fontSize: 13),
              decoration: const InputDecoration(
                isDense: true,
                border: OutlineInputBorder(),
              ),
              items: _cohortOptions
                  .map((c) => DropdownMenuItem<String>(
                        value: c,
                        child: Tooltip(
                          message: _cohortTooltip(c),
                          child: Text(c),
                        ),
                      ))
                  .toList(),
              onChanged: (v) => setState(() => _cohort = v ?? _cohort),
            ),
            const SizedBox(height: 12),
            const Text(
              'Population type',
              style: TextStyle(color: _D.textDim, fontSize: 11),
            ),
            const SizedBox(height: 4),
            DropdownButtonFormField<String>(
              initialValue: _population,
              dropdownColor: _D.bgElev,
              style: const TextStyle(color: _D.text, fontSize: 13),
              hint: const Text(
                'Select population…',
                style: TextStyle(color: _D.textDim, fontSize: 12),
              ),
              decoration: const InputDecoration(
                isDense: true,
                border: OutlineInputBorder(),
              ),
              items: _populationOptions
                  .map((p) => DropdownMenuItem<String>(
                        value: p,
                        child: Tooltip(
                          message: p == 'adult_survivor'
                              ? 'Adults aged 18+ with informed consent.'
                              : 'Minor selections require guardian consent '
                                  'per Gap O.',
                          child: Text(p),
                        ),
                      ))
                  .toList(),
              onChanged: (v) => setState(() => _population = v),
            ),
            const SizedBox(height: 16),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Checkbox(
                  value: _consent,
                  fillColor: WidgetStateProperty.resolveWith((states) {
                    if (states.contains(WidgetState.selected)) {
                      return _D.cyan;
                    }
                    return null;
                  }),
                  checkColor: _D.bgVoid,
                  onChanged: (v) => setState(() => _consent = v ?? false),
                ),
                const Expanded(
                  child: Padding(
                    padding: EdgeInsets.only(top: 12),
                    child: Text(
                      'I confirm this client has provided informed consent '
                      'for Sensitive Clinical Bridge enrollment, including '
                      'data collection, clinician review of detector outputs, '
                      'and HIPAA Right of Access per Gap N.',
                      style: TextStyle(color: _D.text, fontSize: 11),
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancel', style: TextStyle(color: _D.textDim)),
        ),
        ElevatedButton(
          onPressed: _canSubmit
              ? () {
                  Navigator.of(context).pop(_EnrollmentDialogResult(
                    cohortLabel: _cohort,
                    populationType: _population!,
                    informedConsentConfirmed: _consent,
                  ));
                }
              : null,
          style: ElevatedButton.styleFrom(
            backgroundColor: _D.cyan,
            disabledBackgroundColor: _D.cyan.withValues(alpha: 0.3),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(20),
            ),
          ),
          child: const Text(
            'Enroll Client',
            style: TextStyle(
              color: Colors.black,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
      ],
    );
  }
}

class _SectionCard extends StatefulWidget {
  final String title;
  final Widget child;
  final Widget? badge;
  const _SectionCard({
    required this.title,
    required this.child,
    this.badge,
  });

  @override
  State<_SectionCard> createState() => _SectionCardState();
}

class _SectionCardState extends State<_SectionCard> {
  bool _expanded = false; // Note 3: collapsed-by-default

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(
        color: _D.bgCard,
        border: Border.all(color: _D.border),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          InkWell(
            onTap: () => setState(() => _expanded = !_expanded),
            child: Padding(
              padding: const EdgeInsets.symmetric(
                horizontal: 14,
                vertical: 12,
              ),
              child: Row(
                children: [
                  Icon(
                    _expanded ? Icons.expand_less : Icons.expand_more,
                    color: _D.gold,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      widget.title,
                      style: const TextStyle(
                        color: _D.gold,
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                  if (widget.badge != null) widget.badge!,
                ],
              ),
            ),
          ),
          if (_expanded)
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
              child: widget.child,
            ),
        ],
      ),
    );
  }
}

class _Badge extends StatelessWidget {
  final String label;
  final Color color;
  const _Badge({required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        border: Border.all(color: color.withValues(alpha: 0.6)),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: color,
          fontSize: 10,
          fontWeight: FontWeight.w600,
          letterSpacing: 0.4,
        ),
      ),
    );
  }
}

class _Kv {
  final String k;
  final String v;
  const _Kv(this.k, this.v);
}

class _ReadOnlyKv extends StatelessWidget {
  final List<_Kv> rows;
  const _ReadOnlyKv({required this.rows});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: rows
          .map(
            (r) => Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SizedBox(
                    width: 130,
                    child: Text(
                      r.k,
                      style: const TextStyle(
                        color: _D.textDim,
                        fontSize: 12,
                      ),
                    ),
                  ),
                  Expanded(
                    child: Text(
                      r.v,
                      style: const TextStyle(color: _D.text, fontSize: 13),
                    ),
                  ),
                ],
              ),
            ),
          )
          .toList(),
    );
  }
}

class _ListTile extends StatelessWidget {
  final String title;
  final String subtitle;
  final String? trailing;
  const _ListTile({
    required this.title,
    required this.subtitle,
    this.trailing,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(color: _D.text, fontSize: 13),
                ),
                const SizedBox(height: 2),
                Text(
                  subtitle,
                  style: const TextStyle(color: _D.textDim, fontSize: 11),
                ),
              ],
            ),
          ),
          if (trailing != null)
            Padding(
              padding: const EdgeInsets.only(left: 8),
              child: Text(
                trailing!,
                style: const TextStyle(color: _D.cyan, fontSize: 12),
              ),
            ),
        ],
      ),
    );
  }
}

class _Empty extends StatelessWidget {
  final String message;
  const _Empty(this.message);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Text(
        message,
        style: const TextStyle(color: _D.textDim, fontSize: 12),
      ),
    );
  }
}

// =============================================================================
// THRESHOLD PRESET SLIDER (Note 3)
// Always visible: current value, population preset marker, "reset to preset"
// affordance when current value differs from preset.
// =============================================================================

class _PresetSlider extends StatefulWidget {
  final String label;
  final double value;
  final double preset;
  final double min;
  final double max;
  final String? population;
  final bool interactive;
  final ValueChanged<double> onCommit;

  const _PresetSlider({
    required this.label,
    required this.value,
    required this.preset,
    required this.min,
    required this.max,
    required this.population,
    this.interactive = true,
    required this.onCommit,
  });

  @override
  State<_PresetSlider> createState() => _PresetSliderState();
}

class _PresetSliderState extends State<_PresetSlider> {
  late double _draft;

  @override
  void initState() {
    super.initState();
    _draft = widget.value;
  }

  @override
  void didUpdateWidget(covariant _PresetSlider old) {
    super.didUpdateWidget(old);
    if ((old.value - widget.value).abs() > 1e-9) {
      _draft = widget.value;
    }
  }

  @override
  Widget build(BuildContext context) {
    final isOverridden = (_draft - widget.preset).abs() > 1e-3;
    final population = widget.population ?? 'general_trauma';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                widget.label,
                style: const TextStyle(color: _D.text, fontSize: 13),
              ),
            ),
            Text(
              _draft.toStringAsFixed(2),
              style: const TextStyle(color: _D.cyan, fontSize: 13),
            ),
          ],
        ),
        const SizedBox(height: 4),
        Stack(
          alignment: Alignment.centerLeft,
          children: [
            SliderTheme(
              data: SliderTheme.of(context).copyWith(
                activeTrackColor: _D.gold,
                inactiveTrackColor: _D.border,
                thumbColor: _D.goldBright,
                overlayColor: _D.gold.withValues(alpha: 0.2),
              ),
              child: Slider(
                min: widget.min,
                max: widget.max,
                value: _draft.clamp(widget.min, widget.max),
                onChanged: widget.interactive
                    ? (v) => setState(() => _draft = v)
                    : null,
                onChangeEnd: widget.interactive
                    ? (v) {
                        widget.onCommit(v);
                      }
                    : null,
              ),
            ),
            // Preset marker — vertical pill aligned to the preset position.
            // Computed in pixels at layout time.
            LayoutBuilder(
              builder: (ctx, c) {
                final t =
                    ((widget.preset - widget.min) / (widget.max - widget.min))
                        .clamp(0.0, 1.0);
                // Slider has standard 24-px thumb padding; subtract to align.
                const thumbPadding = 24.0;
                final usable = c.maxWidth - thumbPadding * 2;
                final dx = thumbPadding + usable * t;
                return IgnorePointer(
                  child: Padding(
                    padding: EdgeInsets.only(left: dx - 1.5),
                    child: Container(
                      width: 3,
                      height: 18,
                      color: _D.purple,
                    ),
                  ),
                );
              },
            ),
          ],
        ),
        Row(
          children: [
            Container(
              width: 12,
              height: 4,
              color: _D.purple,
            ),
            const SizedBox(width: 6),
            Text(
              'preset $population: ${widget.preset.toStringAsFixed(2)}',
              style: const TextStyle(color: _D.textDim, fontSize: 11),
            ),
            const Spacer(),
            if (isOverridden && widget.interactive)
              TextButton(
                style: TextButton.styleFrom(
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  minimumSize: const Size(0, 30),
                  visualDensity: VisualDensity.compact,
                  foregroundColor: _D.purple,
                ),
                onPressed: () {
                  setState(() => _draft = widget.preset);
                  widget.onCommit(widget.preset);
                },
                child: const Text(
                  'reset to preset',
                  style: TextStyle(fontSize: 11),
                ),
              ),
          ],
        ),
      ],
    );
  }
}

// =============================================================================
// SAFE-SILENCE PANEL (two-step gate UI)
// =============================================================================

class _SafeSilencePanel extends StatefulWidget {
  final SafeSilenceState state;
  final bool isAdmin;
  final String principalUsername;
  final bool hasActiveCodeword;
  final Future<void> Function(String reason) onPropose;
  final Future<void> Function(String proposalId, String? note) onApprove;
  final Future<void> Function() onCancelPending;
  final Future<void> Function() onRejectPending;
  final Future<void> Function() onRevokeActive;

  const _SafeSilencePanel({
    required this.state,
    required this.isAdmin,
    required this.principalUsername,
    required this.hasActiveCodeword,
    required this.onPropose,
    required this.onApprove,
    required this.onCancelPending,
    required this.onRejectPending,
    required this.onRevokeActive,
  });

  @override
  State<_SafeSilencePanel> createState() => _SafeSilencePanelState();
}

class _SafeSilencePanelState extends State<_SafeSilencePanel> {
  final _reasonCtrl = TextEditingController();
  final _approveNoteCtrl = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _reasonCtrl.dispose();
    _approveNoteCtrl.dispose();
    super.dispose();
  }

  bool get _isProposer {
    final pid = widget.state.proposerId ?? '';
    final me = widget.principalUsername;
    return pid.isNotEmpty && me.isNotEmpty && pid == me;
  }

  @override
  Widget build(BuildContext context) {
    final s = widget.state;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _ReadOnlyKv(rows: [
          _Kv('State', s.state),
          if (s.proposerId != null) _Kv('Proposed by', s.proposerId!),
          if (s.proposedAt != null) _Kv('Proposed at', s.proposedAt!),
          if (s.approverId != null) _Kv('Approved by', s.approverId!),
          if (s.approvedAt != null) _Kv('Approved at', s.approvedAt!),
          if (s.expiresAt != null) _Kv('Expires at', s.expiresAt!),
          if (s.daysUntilExpiry != null)
            _Kv('Days remaining', '${s.daysUntilExpiry}'),
        ]),
        const SizedBox(height: 12),
        if (!widget.hasActiveCodeword)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
            margin: const EdgeInsets.only(bottom: 10),
            decoration: BoxDecoration(
              color: _D.red.withValues(alpha: 0.1),
              border: Border.all(color: _D.red.withValues(alpha: 0.6)),
              borderRadius: BorderRadius.circular(6),
            ),
            child: const Text(
              'Approval is BLOCKED until at least one active codeword is set. '
              'Add a codeword first; safety net must precede silence.',
              style: TextStyle(color: _D.red, fontSize: 11),
            ),
          ),
        if (s.isInactive)
          _coachOnly(
            child: _proposeForm(),
          ),
        if (s.isPending)
          widget.isAdmin ? _adminPendingPanel(s) : _coachPendingPanel(),
        if (s.isActive) _activePanel(),
      ],
    );
  }

  Widget _coachPendingPanel() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const _Empty(
          'Awaiting admin approval in a separate session.',
        ),
        if (_isProposer) ...[
          const SizedBox(height: 10),
          Align(
            alignment: Alignment.centerRight,
            child: TextButton(
              onPressed: _busy
                  ? null
                  : () async {
                      setState(() => _busy = true);
                      try {
                        await widget.onCancelPending();
                      } finally {
                        if (mounted) setState(() => _busy = false);
                      }
                    },
              child: const Text(
                'Cancel Proposal',
                style: TextStyle(color: _D.red),
              ),
            ),
          ),
        ],
      ],
    );
  }

  Widget _adminPendingPanel(SafeSilenceState s) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _approveForm(s.proposalId ?? ''),
        const SizedBox(height: 8),
        Align(
          alignment: Alignment.centerRight,
          child: TextButton(
            onPressed: _busy
                ? null
                : () async {
                    setState(() => _busy = true);
                    try {
                      await widget.onRejectPending();
                    } finally {
                      if (mounted) setState(() => _busy = false);
                    }
                  },
            child: const Text(
              'Reject Proposal',
              style: TextStyle(color: _D.red),
            ),
          ),
        ),
      ],
    );
  }

  Widget _activePanel() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const _Empty(
          'Safe Silence is active. The agent will not initiate outreach. '
          'Codeword listener remains armed.',
        ),
        if (widget.isAdmin) ...[
          const SizedBox(height: 10),
          Align(
            alignment: Alignment.centerRight,
            child: TextButton(
              onPressed: _busy
                  ? null
                  : () async {
                      setState(() => _busy = true);
                      try {
                        await widget.onRevokeActive();
                      } finally {
                        if (mounted) setState(() => _busy = false);
                      }
                    },
              child: const Text(
                'Revoke Silence Mode',
                style: TextStyle(color: _D.red),
              ),
            ),
          ),
        ],
      ],
    );
  }

  Widget _coachOnly({required Widget child}) {
    if (widget.isAdmin) {
      return const _Empty(
        'Admin role cannot propose. Switch to clinician session to propose.',
      );
    }
    return child;
  }

  Widget _proposeForm() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TextField(
          controller: _reasonCtrl,
          maxLines: 3,
          maxLength: 500,
          style: const TextStyle(color: _D.text, fontSize: 13),
          decoration: const InputDecoration(
            hintText:
                'Clinical reason (no PII; this text is screened server-side)',
            hintStyle: TextStyle(color: _D.textDim, fontSize: 12),
            filled: true,
            fillColor: _D.bgElev,
            border: OutlineInputBorder(),
          ),
        ),
        const SizedBox(height: 8),
        Align(
          alignment: Alignment.centerRight,
          child: ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: _D.gold,
              foregroundColor: _D.bgVoid,
            ),
            onPressed: _busy
                ? null
                : () async {
                    final r = _reasonCtrl.text.trim();
                    if (r.isEmpty) return;
                    setState(() => _busy = true);
                    try {
                      await widget.onPropose(r);
                      _reasonCtrl.clear();
                    } finally {
                      if (mounted) setState(() => _busy = false);
                    }
                  },
            child: const Text('Propose'),
          ),
        ),
      ],
    );
  }

  Widget _approveForm(String proposalId) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          'Approving proposal id: $proposalId',
          style: const TextStyle(color: _D.cyan, fontSize: 12),
        ),
        const SizedBox(height: 6),
        TextField(
          controller: _approveNoteCtrl,
          maxLines: 2,
          maxLength: 500,
          style: const TextStyle(color: _D.text, fontSize: 13),
          decoration: const InputDecoration(
            hintText: 'Approver note (optional, screened server-side)',
            hintStyle: TextStyle(color: _D.textDim, fontSize: 12),
            filled: true,
            fillColor: _D.bgElev,
            border: OutlineInputBorder(),
          ),
        ),
        const SizedBox(height: 8),
        Align(
          alignment: Alignment.centerRight,
          child: ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: _D.cyan,
              foregroundColor: _D.bgVoid,
            ),
            onPressed: _busy
                ? null
                : () async {
                    setState(() => _busy = true);
                    try {
                      final note = _approveNoteCtrl.text.trim();
                      await widget.onApprove(
                        proposalId,
                        note.isEmpty ? null : note,
                      );
                      _approveNoteCtrl.clear();
                    } finally {
                      if (mounted) setState(() => _busy = false);
                    }
                  },
            child: const Text('Approve in This Session'),
          ),
        ),
      ],
    );
  }
}

// =============================================================================
// ACTIVITY LOG PANEL (Note 2)
// =============================================================================

class _ActivityLogPanel extends StatelessWidget {
  final List<ActivityEvent> events;
  final bool loading;
  final String? error;
  final int days;
  final bool exhausted;
  final ValueChanged<int> onChangeDays;
  final VoidCallback onLoadOlder;

  const _ActivityLogPanel({
    required this.events,
    required this.loading,
    required this.error,
    required this.days,
    required this.exhausted,
    required this.onChangeDays,
    required this.onLoadOlder,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            const Text(
              'Window:',
              style: TextStyle(color: _D.textDim, fontSize: 12),
            ),
            const SizedBox(width: 8),
            for (final d in const [7, 30, 90, 365])
              Padding(
                padding: const EdgeInsets.only(right: 6),
                child: ChoiceChip(
                  label: Text(
                    '${d}d',
                    style: TextStyle(
                      color: days == d ? _D.bgVoid : _D.gold,
                      fontSize: 11,
                    ),
                  ),
                  selected: days == d,
                  onSelected: (sel) {
                    if (sel) onChangeDays(d);
                  },
                  selectedColor: _D.gold,
                  backgroundColor: _D.bgElev,
                  side: const BorderSide(color: _D.border),
                ),
              ),
          ],
        ),
        const SizedBox(height: 8),
        if (error != null)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Text(
              error!,
              style: const TextStyle(color: _D.red, fontSize: 11),
            ),
          ),
        if (events.isEmpty && !loading)
          const _Empty('No activity in the selected window.'),
        for (final e in events) _ActivityRow(event: e),
        const SizedBox(height: 8),
        Center(
          child: loading
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(
                    color: _D.gold,
                    strokeWidth: 2,
                  ),
                )
              : exhausted
                  ? const Text(
                      'End of log',
                      style: TextStyle(color: _D.textDim, fontSize: 11),
                    )
                  : TextButton(
                      onPressed: onLoadOlder,
                      style: TextButton.styleFrom(
                        foregroundColor: _D.gold,
                      ),
                      child: const Text('load older'),
                    ),
        ),
      ],
    );
  }
}

class _ActivityRow extends StatelessWidget {
  final ActivityEvent event;
  const _ActivityRow({required this.event});

  @override
  Widget build(BuildContext context) {
    final severity = event.eventSeverity ?? 'info';
    final color = switch (severity) {
      'critical' => _D.red,
      'high' => _D.red,
      'moderate' => _D.yellow,
      'low' => _D.cyan,
      _ => _D.textDim,
    };
    final title = event.eventType;
    final subtitle = event.isAdminRedacted
        ? '[admin-only event — payload redacted by server]'
        : (event.decisionSummary ?? '');
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
      decoration: BoxDecoration(
        color: _D.bgElev,
        border: Border(
          left: BorderSide(color: color, width: 3),
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(color: _D.text, fontSize: 12),
                ),
                if (subtitle.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Text(
                      subtitle,
                      style: TextStyle(
                        color: event.isAdminRedacted ? _D.textDim : _D.textDim,
                        fontStyle: event.isAdminRedacted
                            ? FontStyle.italic
                            : FontStyle.normal,
                        fontSize: 11,
                      ),
                    ),
                  ),
                Padding(
                  padding: const EdgeInsets.only(top: 2),
                  child: Text(
                    '${event.occurredAt ?? ''} · ${event.recordedBy ?? ''}',
                    style: const TextStyle(color: _D.textDim, fontSize: 10),
                  ),
                ),
              ],
            ),
          ),
          _Badge(label: severity, color: color),
        ],
      ),
    );
  }
}
