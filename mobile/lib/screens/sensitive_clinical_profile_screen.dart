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
import 'package:http/http.dart' as http;

import '../config/app_config.dart' as cfg;

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
    _NOVELTY_PRESETS[populationType ?? ''] ?? _NOVELTY_PRESETS['general_trauma']!;
double _arousalPreset(String? populationType) =>
    _AROUSAL_PRESETS[populationType ?? ''] ?? _AROUSAL_PRESETS['general_trauma']!;

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
  final SafeSilenceState safeSilence;
  final List<Codeword> codewords;
  final List<TriggerDate> triggerDates;
  final List<PolyvictimLayer> polyvictimLayers;
  final List<LegalCase> legalStatus;

  /// Population type drives the threshold presets. Not part of the GET
  /// response surface yet; default to general_trauma per Note 3 banner rule.
  final String? populationType;

  SensitiveProfile({
    required this.userId,
    required this.embodimentPhase,
    required this.noveltyThreshold,
    required this.arousalThreshold,
    required this.substanceStatus,
    required this.safeSilence,
    required this.codewords,
    required this.triggerDates,
    required this.polyvictimLayers,
    required this.legalStatus,
    required this.populationType,
  });

  factory SensitiveProfile.fromJson(Map<String, dynamic> j) {
    return SensitiveProfile(
      userId: (j['user_id'] ?? '').toString(),
      embodimentPhase: j['embodiment_phase'] as String?,
      noveltyThreshold: _d(j['novelty_threshold']),
      arousalThreshold: _d(j['arousal_threshold']),
      substanceStatus: j['substance_status'] as String?,
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
    );
  }

  /// Note 1: badge counts/strings derived from the SAME response object.
  int get activeCodewordCount => codewords.where((c) => c.active).length;
  int get activePolyvictimCount =>
      polyvictimLayers.where((p) => p.active).length;
  String? get highestPolyvictimSeverity {
    const order = ['critical', 'high', 'moderate', 'low'];
    for (final lvl in order) {
      if (polyvictimLayers.any((p) => p.active && p.severity == lvl)) return lvl;
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
      throw _ApiError(resp.statusCode, _decodeReason(resp.body));
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
      throw _ApiError(resp.statusCode, _decodeReason(resp.body));
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
    double value,
  ) async {
    final path = which == 'novelty'
        ? 'novelty-threshold'
        : 'arousal-threshold';
    final uri = Uri.parse('$_base/api/coach/sensitive-profile/$userId/$path');
    final body = jsonEncode({which: value});
    final resp = await http
        .put(uri, headers: _headers, body: body)
        .timeout(const Duration(seconds: 10));
    if (resp.statusCode != 200) {
      throw _ApiError(resp.statusCode, _decodeReason(resp.body));
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
      throw _ApiError(resp.statusCode, _decodeReason(resp.body));
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
      throw _ApiError(resp.statusCode, _decodeReason(resp.body));
    }
  }

  String _decodeReason(String body) {
    try {
      final j = jsonDecode(body);
      if (j is Map && j['detail'] is Map) {
        final reason = (j['detail'] as Map)['reason'];
        if (reason != null) return reason.toString();
      }
      if (j is Map && j['detail'] != null) return j['detail'].toString();
    } catch (_) {}
    return body.length > 240 ? '${body.substring(0, 240)}…' : body;
  }
}

class _ApiError implements Exception {
  final int status;
  final String reason;
  _ApiError(this.status, this.reason);
  @override
  String toString() => 'API $status: $reason';
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

  const SensitiveClinicalProfileScreen({
    super.key,
    required this.currentUserProfile,
    required this.targetUserId,
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

  Future<void> _loadProfile() async {
    setState(() {
      _loading = true;
      _loadError = null;
    });
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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _D.bgVoid,
      appBar: AppBar(
        backgroundColor: _D.bgCard,
        elevation: 0,
        title: Text(
          'Sensitive Profile · ${widget.targetUserId}',
          style: const TextStyle(color: _D.gold, fontSize: 16),
        ),
        actions: [
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh, color: _D.gold),
            onPressed: _loading ? null : _loadProfile,
          ),
        ],
      ),
      body: _buildBody(),
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
                child:
                    const Text('Retry', style: TextStyle(color: _D.gold)),
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
          if (p.populationType == null)
            const _PopulationTypeBanner(),
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
    final color = (status == 'crisis' || status == 'active_use')
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
      final label =
          d == null ? 'active' : 'active · ${d}d';
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

  Widget _embodimentBody(SensitiveProfile p) {
    return _ReadOnlyKv(rows: [
      _Kv('Current phase', p.embodimentPhase ?? '—'),
      const _Kv(
        'Allowed values',
        'repair · transitioning · ready',
      ),
    ]);
  }

  Widget _thresholdsBody(SensitiveProfile p) {
    final pop = p.populationType;
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
          onCommit: (v) => _commitThreshold('arousal', v),
        ),
      ],
    );
  }

  Future<void> _commitThreshold(String which, double value) async {
    try {
      await _api.putThreshold(widget.targetUserId, which, value);
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
          content: Text('Update failed: $e',
              style: const TextStyle(color: Colors.white)),
        ),
      );
    }
  }

  Widget _substanceBody(SensitiveProfile p) {
    return _ReadOnlyKv(rows: [
      _Kv('Current status', p.substanceStatus ?? 'none'),
      const _Kv('Allowed values', 'none · recovery · active_use · crisis'),
    ]);
  }

  Widget _codewordBody(SensitiveProfile p) {
    if (p.codewords.isEmpty) {
      return const _Empty('No codewords set.');
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: p.codewords
          .map((c) => _ListTile(
                title: c.codewordLabel ?? c.hashPrefix,
                subtitle:
                    '${c.codewordType ?? '—'} · ${c.active ? 'active' : 'inactive'}'
                    '${c.triggersMandatoryReporting ? ' · mandatory-report' : ''}',
                trailing: c.triggerCount > 0 ? '×${c.triggerCount}' : null,
              ))
          .toList(),
    );
  }

  Widget _triggerDateBody(SensitiveProfile p) {
    if (p.triggerDates.isEmpty) return const _Empty('No trigger dates set.');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: p.triggerDates
          .map((t) => _ListTile(
                title: t.triggerDate,
                subtitle:
                    '${t.dateType ?? '—'} · severity ${t.severity ?? '—'}'
                    '${t.recurringAnnually ? ' · annual' : ''}'
                    '${t.active ? '' : ' · inactive'}',
              ))
          .toList(),
    );
  }

  Widget _polyvictimBody(SensitiveProfile p) {
    if (p.polyvictimLayers.isEmpty) {
      return const _Empty('No polyvictim layers recorded.');
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: p.polyvictimLayers
          .map((l) => _ListTile(
                title: l.layerType,
                subtitle:
                    'severity ${l.severity}${l.active ? '' : ' · inactive'}',
              ))
          .toList(),
    );
  }

  Widget _legalBody(SensitiveProfile p) {
    if (p.legalStatus.isEmpty) return const _Empty('No legal cases on file.');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: p.legalStatus
          .map((c) => _ListTile(
                title: '${c.caseType} · ${c.caseStatus}',
                subtitle: c.nextEventDate != null
                    ? 'next event: ${c.nextEventDate}'
                    : 'no scheduled event',
              ))
          .toList(),
    );
  }

  Widget _safeSilenceBody(SensitiveProfile p) {
    final s = p.safeSilence;
    return _SafeSilencePanel(
      state: s,
      isAdmin: _isAdmin,
      hasActiveCodeword: p.activeCodewordCount > 0,
      onPropose: _onProposeSafeSilence,
      onApprove: _onApproveSafeSilence,
    );
  }

  Future<void> _onProposeSafeSilence(String reason) async {
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
    final msg = e.toString();
    String hint = msg;
    // Surface the structured 409s as inline-friendly text.
    if (msg.contains('same_session_violation')) {
      hint =
          'Same-session block: a different user must approve in a separate session.';
    } else if (msg.contains('requires_codeword')) {
      hint =
          'At least one active codeword must be set before approval can succeed.';
    } else if (msg.contains('stale_proposal') || msg.contains('proposal_id')) {
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
  final ValueChanged<double> onCommit;

  const _PresetSlider({
    required this.label,
    required this.value,
    required this.preset,
    required this.min,
    required this.max,
    required this.population,
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
                onChanged: (v) => setState(() => _draft = v),
                onChangeEnd: (v) {
                  widget.onCommit(v);
                },
              ),
            ),
            // Preset marker — vertical pill aligned to the preset position.
            // Computed in pixels at layout time.
            LayoutBuilder(
              builder: (ctx, c) {
                final t = ((widget.preset - widget.min) /
                        (widget.max - widget.min))
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
            if (isOverridden)
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
  final bool hasActiveCodeword;
  final Future<void> Function(String reason) onPropose;
  final Future<void> Function(String proposalId, String? note) onApprove;

  const _SafeSilencePanel({
    required this.state,
    required this.isAdmin,
    required this.hasActiveCodeword,
    required this.onPropose,
    required this.onApprove,
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
          widget.isAdmin
              ? _approveForm(s.proposalId ?? '')
              : const _Empty(
                  'Awaiting admin approval in a separate session.',
                ),
        if (s.isActive)
          const _Empty(
            'Safe Silence is active. The agent will not initiate outreach. '
            'Codeword listener remains armed.',
          ),
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
                        color: event.isAdminRedacted
                            ? _D.textDim
                            : _D.textDim,
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
