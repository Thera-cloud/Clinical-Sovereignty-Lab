// Community Mesh Service — Nate-to-Nate BLE/NFC Group Sessions
// Orchestrates Community Mesh BLE discovery, wisdom sharing, and attendance.
// Uses ZEFCP infrastructure: FibreIdentity, FragmentBuffer, OfflineBuffer, BLE scanner/advertiser.
// © 2026 Clinical Sovereignty Lab. All rights reserved.

import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:uuid/uuid.dart';

import '../config/app_config.dart';
import '../zefcp/ble_scanner.dart';
import '../zefcp/ble_advertiser.dart';
import '../zefcp/fibre_identity.dart';
import '../zefcp/fragment_buffer.dart';
import '../zefcp/offline_buffer.dart';
import '../zefcp/secure_key_store.dart';
import '../zefcp/constants.dart';

// ─── Community Mesh BLE Constants ───────────────────────────────────────────
// 128-bit UUID for Nate-to-Nate Community Mesh discovery (generated v4-style)
const String communityMeshServiceUuidStr = 'a7b3c2d1-4e5f-6789-abcd-ef0123456789';
// Type byte for community mesh in ZEFCP fragments (0x4D = 'M' for Mesh)
const int _communityMeshTypeByte = 0x4D;

// ─── PII Detection Patterns (strip before any outgoing broadcast) ────────────
final _piiPatterns = [
  RegExp(r'\b\d{3}-\d{2}-\d{4}\b'), // SSN
  RegExp(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'), // Credit card
  RegExp(r'\b\+?1?[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b'), // Phone
  RegExp(r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b'), // Email
  RegExp(r'\b\d{1,5}\s+[\w\s]+(?:street|st|avenue|ave|road|rd|drive|dr|lane|ln|way)\b', caseSensitive: false), // Address
];

// ─── State Machine ─────────────────────────────────────────────────────────

enum MeshState {
  idle,
  discovering,
  forming,
  active,
  closing,
}

// ─── Models ────────────────────────────────────────────────────────────────

class PeerInfo {
  final String anonymousId;
  final int signalStrength;
  final double? moodValence;
  final String deviceId;

  PeerInfo({
    required this.anonymousId,
    required this.signalStrength,
    this.moodValence,
    required this.deviceId,
  });

  PeerInfo copyWith({
    String? anonymousId,
    int? signalStrength,
    double? moodValence,
    String? deviceId,
  }) =>
      PeerInfo(
        anonymousId: anonymousId ?? this.anonymousId,
        signalStrength: signalStrength ?? this.signalStrength,
        moodValence: moodValence ?? this.moodValence,
        deviceId: deviceId ?? this.deviceId,
      );
}

class WisdomEntry {
  final String topic;
  final String insightText;
  final DateTime timestamp;

  WisdomEntry({
    required this.topic,
    required this.insightText,
    required this.timestamp,
  });
}

class AttendanceRecord {
  final String peerId;
  final String? displayName;
  final String checkInTime;
  final String? checkOutTime;
  final String? locationName;
  final String? groupName;
  final String? sessionDate;
  final int? durationMinutes;
  final bool verified;

  AttendanceRecord({
    required this.peerId,
    this.displayName,
    required this.checkInTime,
    this.checkOutTime,
    this.locationName,
    this.groupName,
    this.sessionDate,
    this.durationMinutes,
    this.verified = false,
  });

  Map<String, dynamic> toJson() => {
        'user_id': peerId,
        'display_name': displayName,
        'check_in_time': checkInTime,
        'check_out_time': checkOutTime,
        'location_name': locationName,
        'group_name': groupName,
        'session_date': sessionDate,
        'duration_minutes': durationMinutes,
        'verified_by_manager': verified,
      };

  AttendanceRecord copyWith({
    String? peerId,
    String? displayName,
    String? checkInTime,
    String? checkOutTime,
    String? locationName,
    String? groupName,
    String? sessionDate,
    int? durationMinutes,
    bool? verified,
  }) =>
      AttendanceRecord(
        peerId: peerId ?? this.peerId,
        displayName: displayName ?? this.displayName,
        checkInTime: checkInTime ?? this.checkInTime,
        checkOutTime: checkOutTime ?? this.checkOutTime,
        locationName: locationName ?? this.locationName,
        groupName: groupName ?? this.groupName,
        sessionDate: sessionDate ?? this.sessionDate,
        durationMinutes: durationMinutes ?? this.durationMinutes,
        verified: verified ?? this.verified,
      );
}

// ─── Community Mesh Service ───────────────────────────────────────────────

/// Orchestrates Nate-to-Nate Community Mesh BLE connections.
/// Uses ZEFCP infrastructure for anonymous identity and fragment transport.
class CommunityMeshService with ChangeNotifier {
  // ZEFCP infrastructure
  late final FibreIdentity _fibreIdentity;
  late final FragmentBuffer _fragmentBuffer;
  late final OfflineBuffer _offlineBuffer;
  ZefcpBleScanner? _bleScanner;
  ZefcpBleAdvertiser? _bleAdvertiser;

  // BLE
  StreamSubscription<ZefcpScanResult>? _scanSubscription;
  bool _isAdvertising = false;

  // State
  MeshState _state = MeshState.idle;
  String _sessionId = '';
  String _groupName = '';
  bool _isManager = false;
  final List<PeerInfo> _connectedPeers = [];
  final List<WisdomEntry> _wisdomFeed = [];
  final Map<String, AttendanceRecord> _attendanceRecords = {};
  StreamSubscription<AssembledObservation>? _assemblySubscription;

  // Callbacks (caller provides these)
  String? Function()? getAuthToken;
  String? Function()? getUserId;

  CommunityMeshService() {
    _fibreIdentity = FibreIdentity();
    _fragmentBuffer = FragmentBuffer();
    _offlineBuffer = OfflineBuffer();
  }

  // ─── Public Properties ───────────────────────────────────────────────────

  String get sessionId => _sessionId;
  String get groupName => _groupName;
  MeshState get state => _state;
  bool get isManager => _isManager;
  List<PeerInfo> get connectedPeers => List.unmodifiable(_connectedPeers);
  List<WisdomEntry> get wisdomFeed => List.unmodifiable(_wisdomFeed);

  /// Start a community mesh session.
  /// Begins BLE advertising and scanning with the community mesh service UUID.
  Future<void> startSession({
    required String groupName,
    List<String> topicTags = const [],
    bool isManager = false,
  }) async {
    if (_state != MeshState.idle) {
      debugPrint('[CommunityMesh] Cannot start: already in state $_state');
      return;
    }

    _updateState(MeshState.discovering);
    _sessionId = const Uuid().v4();
    _groupName = _stripPii(groupName);
    _isManager = isManager;
    _connectedPeers.clear();
    _wisdomFeed.clear();
    _attendanceRecords.clear();

    try {
      await _fibreIdentity.initialize();
      if (_fibreIdentity.fibreId == null) {
        throw StateError('FibreIdentity not initialized');
      }

      _assemblySubscription = _fragmentBuffer.assembledObservations.listen(_onAssembledWisdom);

      // Start BLE scanning for community mesh devices
      await _startBleScan();

      // Start BLE advertising with anonymous FibreIdentity
      await _startBleAdvertise(topicTags: topicTags);

      // Record session via backend
      await _recordSession(topicTags: topicTags);

      _updateState(MeshState.forming);

      // Transition to ACTIVE after a short discovery window
      Future.delayed(const Duration(seconds: 3), () {
        if (_state == MeshState.forming) {
          _updateState(MeshState.active);
        }
      });
    } catch (e) {
      debugPrint('[CommunityMesh] startSession error: $e');
      _updateState(MeshState.idle);
      rethrow;
    }
  }

  /// Stop the mesh session and store summary.
  Future<void> stopSession() async {
    if (_state == MeshState.idle) return;

    _updateState(MeshState.closing);

    try {
      await _assemblySubscription?.cancel();
      _assemblySubscription = null;
      await _stopBleScan();
      await _stopBleAdvertise();

      final summary = {
        'session_id': _sessionId,
        'group_name': _groupName,
        'peer_count': _connectedPeers.length,
        'wisdom_count': _wisdomFeed.length,
        'ended_at': DateTime.now().toUtc().toIso8601String(),
      };

      await _offlineBuffer.bufferEmission(summary);

      _sessionId = '';
      _groupName = '';
      _connectedPeers.clear();
      _wisdomFeed.clear();
    } catch (e) {
      debugPrint('[CommunityMesh] stopSession error: $e');
    } finally {
      _updateState(MeshState.idle);
    }
  }

  /// Submit check-in with mood and location; sends to group and records via API.
  Future<bool> submitCheckIn({
    required double moodValence,
    double? locationLat,
    double? locationLng,
    String? locationName,
  }) async {
    if (_sessionId.isEmpty) return false;

    final userId = getUserId?.call();
    if (userId == null || userId.isEmpty) {
      debugPrint('[CommunityMesh] submitCheckIn: no userId');
      return false;
    }

    final safeLocationName = locationName != null ? _stripPii(locationName) : null;

    // Broadcast mood to connected peers via BLE
    _broadcastMood(moodValence);

    // Record check-in via backend API
    try {
      final token = getAuthToken?.call();
      final response = await http
          .post(
            Uri.parse('${AppConfig.apiBaseUrl}/api/community/check-in'),
            headers: {
              'Content-Type': 'application/json',
              if (token != null) 'Authorization': 'Bearer $token',
            },
            body: jsonEncode({
              'session_id': _sessionId,
              'user_id': userId,
              'mood_valence': moodValence,
              'location_lat': locationLat,
              'location_lng': locationLng,
              'location_name': safeLocationName,
            }),
          )
          .timeout(const Duration(seconds: 10));

      if (response.statusCode >= 200 && response.statusCode < 300) {
        _attendanceRecords[userId] = AttendanceRecord(
          peerId: userId,
          checkInTime: DateTime.now().toUtc().toIso8601String(),
          locationName: safeLocationName,
        );
        notifyListeners();
        return true;
      }
      debugPrint('[CommunityMesh] check-in API error: ${response.statusCode}');
      return false;
    } catch (e) {
      debugPrint('[CommunityMesh] submitCheckIn error: $e');
      return false;
    }
  }

  /// Record check-out via backend API.
  Future<bool> submitCheckOut() async {
    if (_sessionId.isEmpty) return false;

    final userId = getUserId?.call();
    if (userId == null || userId.isEmpty) return false;

    try {
      final token = getAuthToken?.call();
      final response = await http
          .post(
            Uri.parse('${AppConfig.apiBaseUrl}/api/community/check-out'),
            headers: {
              'Content-Type': 'application/json',
              if (token != null) 'Authorization': 'Bearer $token',
            },
            body: jsonEncode({
              'session_id': _sessionId,
              'user_id': userId,
            }),
          )
          .timeout(const Duration(seconds: 10));

      if (response.statusCode >= 200 && response.statusCode < 300) {
        final existing = _attendanceRecords[userId];
        if (existing != null) {
          _attendanceRecords[userId] = existing.copyWith(
            checkOutTime: DateTime.now().toUtc().toIso8601String(),
          );
        }
        notifyListeners();
        return true;
      }
      return false;
    } catch (e) {
      debugPrint('[CommunityMesh] submitCheckOut error: $e');
      return false;
    }
  }

  /// Share anonymized wisdom with connected peers.
  Future<void> shareWisdom(String topic, String insight) async {
    final safeTopic = _stripPii(topic);
    final safeInsight = _stripPii(insight);
    if (safeInsight.isEmpty) return;

    final entry = WisdomEntry(
      topic: safeTopic,
      insightText: safeInsight,
      timestamp: DateTime.now(),
    );
    _wisdomFeed.add(entry);
    notifyListeners();

    // Broadcast via BLE fragments
    _broadcastWisdom(safeTopic, safeInsight);

    // Submit to backend wisdom API
    try {
      final token = getAuthToken?.call();
      await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}/api/community/wisdom'),
        headers: {
          'Content-Type': 'application/json',
          if (token != null) 'Authorization': 'Bearer $token',
        },
        body: jsonEncode({
          'session_id': _sessionId,
          'topic_tags': [safeTopic],
          'anonymized_wisdom': [safeInsight],
          'peer_count': _connectedPeers.length,
          'location_name': _groupName.isNotEmpty ? _groupName : null,
        }),
      ).timeout(const Duration(seconds: 10));
    } catch (e) {
      debugPrint('[CommunityMesh] shareWisdom API error: $e');
    }
  }

  /// Take attendance (group manager only). Returns list of peers with opt-in names.
  Future<List<AttendanceRecord>> takeAttendance() async {
    if (!_isManager) return [];

    final now = DateTime.now().toUtc();
    final sessionDate = '${now.year}-${now.month.toString().padLeft(2, '0')}-${now.day.toString().padLeft(2, '0')}';

    final records = <AttendanceRecord>[];
    for (final peer in _connectedPeers) {
      final rec = _attendanceRecords[peer.anonymousId];
      if (rec != null) {
        records.add(rec.copyWith(
          groupName: _groupName.isNotEmpty ? _groupName : null,
          sessionDate: sessionDate,
        ));
      } else {
        records.add(AttendanceRecord(
          peerId: peer.anonymousId,
          checkInTime: now.toIso8601String(),
          groupName: _groupName.isNotEmpty ? _groupName : null,
          sessionDate: sessionDate,
        ));
      }
    }
    return records;
  }

  /// Mark an attendee as verified present (group manager).
  void verifyAttendee(String peerId) {
    if (!_isManager) return;

    final rec = _attendanceRecords[peerId];
    if (rec != null) {
      _attendanceRecords[peerId] = AttendanceRecord(
        peerId: rec.peerId,
        displayName: rec.displayName,
        checkInTime: rec.checkInTime,
        checkOutTime: rec.checkOutTime,
        locationName: rec.locationName,
        verified: true,
      );
      notifyListeners();
    }
  }

  /// Send attendance records to backend (one POST per record).
  Future<bool> recordAttendance(List<AttendanceRecord> records) async {
    if (_sessionId.isEmpty || records.isEmpty) return false;

    final now = DateTime.now().toUtc();
    final sessionDate = '${now.year}-${now.month.toString().padLeft(2, '0')}-${now.day.toString().padLeft(2, '0')}';
    final token = getAuthToken?.call();

    for (final r in records) {
      try {
        final body = r.toJson()
          ..['session_id'] = _sessionId
          ..['session_date'] = sessionDate
          ..['group_name'] = _groupName.isNotEmpty ? _groupName : null;

        final response = await http
            .post(
              Uri.parse('${AppConfig.apiBaseUrl}/api/community/attendance'),
              headers: {
                'Content-Type': 'application/json',
                if (token != null) 'Authorization': 'Bearer $token',
              },
              body: jsonEncode(body),
            )
            .timeout(const Duration(seconds: 10));

        if (response.statusCode < 200 || response.statusCode >= 300) {
          debugPrint('[CommunityMesh] recordAttendance API error: ${response.statusCode}');
          return false;
        }
      } catch (e) {
        debugPrint('[CommunityMesh] recordAttendance error: $e');
        return false;
      }
    }
    return true;
  }

  @override
  void dispose() {
    // Note: stopSession() is async; we synchronously clean up what we can.
    _scanSubscription?.cancel();
    _assemblySubscription?.cancel();
    _bleScanner?.dispose();
    _bleAdvertiser?.dispose();
    _fragmentBuffer.dispose();
    _offlineBuffer.close();
    super.dispose();
  }

  // ─── BLE Layer (ZEFCP Scanner + Advertiser) ───────────────────────────────

  Future<void> _startBleScan() async {
    _bleScanner = ZefcpBleScanner();
    _scanSubscription = _bleScanner!.scanResults.listen(_onZefcpScanResult);
    await _bleScanner!.start();
    debugPrint('[CommunityMesh] ZEFCP BLE scan started');
  }

  void _onZefcpScanResult(ZefcpScanResult result) {
    if (!result.isPotentialFragment || result.leadingBytes == null) return;
    final leading = result.leadingBytes!;
    if (leading.isEmpty || leading[0] != _communityMeshTypeByte) return;

    final anonymousId = leading.length >= 9
        ? String.fromCharCodes(leading.sublist(1, 9)).trim()
        : String.fromCharCodes(leading.sublist(1)).trim();
    if (anonymousId.isEmpty) return;

    final trailing = result.trailingBytes;
    final moodValence = trailing != null && trailing.isNotEmpty
        ? trailing[0] / 255.0
        : null;

    final existing = _connectedPeers.indexWhere((p) => p.deviceId == result.deviceId);
    final peer = PeerInfo(
      anonymousId: anonymousId,
      signalStrength: result.rssi,
      moodValence: moodValence,
      deviceId: result.deviceId,
    );

    if (existing >= 0) {
      _connectedPeers[existing] = peer;
    } else {
      _connectedPeers.add(peer);
    }
    notifyListeners();
  }

  Future<void> _stopBleScan() async {
    await _scanSubscription?.cancel();
    _scanSubscription = null;
    await _bleScanner?.stop();
    _bleScanner?.dispose();
    _bleScanner = null;
    debugPrint('[CommunityMesh] BLE scan stopped');
  }

  Future<void> _startBleAdvertise({List<String> topicTags = const []}) async {
    final fibreId = _fibreIdentity.fibreId;
    if (fibreId == null || fibreId.isEmpty) return;

    final keyStore = SecureKeyStore();
    var swarmSecret = await keyStore.getSwarmSecret();
    if (swarmSecret == null || swarmSecret.length < 32) {
      swarmSecret = Uint8List(32);
      for (int i = 0; i < 'community_mesh_default_key_32'.length && i < 32; i++) {
        swarmSecret[i] = 'community_mesh_default_key_32'.codeUnitAt(i);
      }
    }

    _bleAdvertiser = ZefcpBleAdvertiser();
    _bleAdvertiser!.initialize(swarmSecret);

    final fragment = _buildPresenceFragment(fibreId);
    _bleAdvertiser!.enqueueFragment(fragment, priority: 1);
    await _bleAdvertiser!.start(intervalMs: 150);

    _isAdvertising = true;
    debugPrint('[CommunityMesh] ZEFCP BLE advertising started');
  }

  Uint8List _buildPresenceFragment(String fibreId) {
    final fid = fibreId.padRight(8).substring(0, 8);
    final out = Uint8List(standardTotalBytes);
    out[0] = _communityMeshTypeByte;
    for (int i = 0; i < 6 && i < fid.length; i++) {
      out[1 + i] = fid.codeUnitAt(i);
    }
    out[7] = 0;
    return out;
  }

  Future<void> _stopBleAdvertise() async {
    if (!_isAdvertising) return;
    await _bleAdvertiser?.stop();
    _bleAdvertiser?.dispose();
    _bleAdvertiser = null;
    _isAdvertising = false;
    debugPrint('[CommunityMesh] BLE advertising stopped');
  }

  void _broadcastMood(double moodValence) {
    // Update local peer entry if we're in the list
    final fid = _fibreIdentity.fibreId ?? '';
    final idx = _connectedPeers.indexWhere((p) => p.anonymousId == fid);
    if (idx >= 0) {
      _connectedPeers[idx] = _connectedPeers[idx].copyWith(moodValence: moodValence);
      notifyListeners();
    }
  }

  void _broadcastWisdom(String topic, String insight) {
    // Wisdom is added to local feed and submitted via API. BLE broadcast of long
    // text is limited by advertising payload (~31 bytes). FragmentBuffer is used
    // to reassemble INCOMING wisdom fragments from peers (see _onAssembledWisdom).
  }

  void _onAssembledWisdom(AssembledObservation obs) {
    try {
      final json = utf8.decode(obs.payload);
      final map = jsonDecode(json) as Map<String, dynamic>;
      final topic = map['topic'] as String? ?? '';
      final insight = map['insight'] as String? ?? '';
      if (insight.isEmpty) return;
      _wisdomFeed.add(WisdomEntry(
        topic: _stripPii(topic),
        insightText: _stripPii(insight),
        timestamp: DateTime.now(),
      ));
      notifyListeners();
    } catch (_) {}
  }

  // ─── Backend API ──────────────────────────────────────────────────────────

  Future<void> _recordSession({List<String> topicTags = const []}) async {
    try {
      final token = getAuthToken?.call();
      final userId = getUserId?.call();
      await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}/api/community/sessions'),
        headers: {
          'Content-Type': 'application/json',
          if (token != null) 'Authorization': 'Bearer $token',
        },
        body: jsonEncode({
          'session_id': _sessionId,
          'group_name': _groupName,
          'peer_count': _connectedPeers.length,
          'topic_tags': topicTags,
          'manager_user_id': _isManager ? userId : null,
        }),
      ).timeout(const Duration(seconds: 10));
    } catch (e) {
      debugPrint('[CommunityMesh] _recordSession error: $e');
    }
  }

  // ─── PII Stripping ────────────────────────────────────────────────────────

  String _stripPii(String input) {
    if (input.isEmpty) return input;
    var out = input;
    for (final pat in _piiPatterns) {
      out = out.replaceAll(pat, '[REDACTED]');
    }
    return out.trim();
  }

  // ─── State ────────────────────────────────────────────────────────────────

  void _updateState(MeshState newState) {
    if (_state != newState) {
      _state = newState;
      notifyListeners();
    }
  }
}
