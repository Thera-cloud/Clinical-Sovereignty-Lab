// =============================================================================
// COMMUNITY MESH SCREEN — Nate-to-Nate Group Sessions
// BLE peer discovery, anonymous wisdom sharing, attendance tracking
// =============================================================================

import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/services.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:http/http.dart' as http;
import 'package:permission_handler/permission_handler.dart';
import 'package:uuid/uuid.dart';

import '../config/app_config.dart';

// Conditional BLE import (not supported on web)
import 'community_mesh_ble.dart' if (dart.library.html) 'community_mesh_ble_stub.dart'
    as ble;

// =============================================================================
// DESIGN TOKENS
// =============================================================================
class _Design {
  static const bgVoid = Color(0xFF050505);
  static const bgChamber = Color(0xFF0A0A0A);
  static const bgElevated = Color(0xFF111111);
  static const gold = Color(0xFFC9A962);
  static const goldBright = Color(0xFFE8D5A3);
  static const goldDim = Color(0xFF8B7355);
  static const cyan = Color(0xFF4ECDC4);
  static const purple = Color(0xFF9D4EDD);
  static const red = Color(0xFFEF4444);
  static const green = Color(0xFF22C55E);
  static const textPrimary = Color(0xFFFFFFFF);
  static const textSecondary = Color(0xFF888888);
}

// =============================================================================
// STATE MACHINE
// =============================================================================
enum CommunityMeshState { IDLE, DISCOVERING, FORMING, ACTIVE, CLOSING }

// =============================================================================
// PEER MODEL
// =============================================================================
class MeshPeer {
  final String id;
  final String displayName;
  final bool verified;
  final bool hasOptInName;

  const MeshPeer({
    required this.id,
    this.displayName = '',
    this.verified = false,
    this.hasOptInName = false,
  });
}

// =============================================================================
// WISDOM INSIGHT MODEL
// =============================================================================
class WisdomInsight {
  final String id;
  final String text;
  final String? topic;
  final int convergenceCount;
  final DateTime? createdAt;

  const WisdomInsight({
    required this.id,
    required this.text,
    this.topic,
    this.convergenceCount = 1,
    this.createdAt,
  });
}

// =============================================================================
// COMMUNITY MESH SCREEN
// =============================================================================
class CommunityMeshScreen extends StatefulWidget {
  final Map<String, dynamic> profile;

  const CommunityMeshScreen({super.key, required this.profile});

  @override
  State<CommunityMeshScreen> createState() => _CommunityMeshScreenState();
}

class _CommunityMeshScreenState extends State<CommunityMeshScreen>
    with TickerProviderStateMixin {
  // ─── Tier gate ───────────────────────────────────────────────────────────
  // ─── State ────────────────────────────────────────────────────────────────
  CommunityMeshState _state = CommunityMeshState.IDLE;
  String? _errorMessage;
  bool _isLoading = false;
  String? _sessionId;
  String _groupName = '';
  final List<String> _topicTags = [];
  final _topicController = TextEditingController();
  final List<MeshPeer> _peers = [];
  final List<WisdomInsight> _wisdomFeed = [];
  double _moodValence = 0.5;
  bool _isManager = false;
  final Map<String, bool> _attendanceVerified = {};
  int _sessionStartSeconds = 0;
  Timer? _durationTimer;

  List<WisdomInsight> get _sharedWisdom => _wisdomFeed;

  // ─── Services ─────────────────────────────────────────────────────────────
  WebSocketChannel? _wsChannel;
  StreamSubscription? _wsSubscription;
  String get _userId => widget.profile['user_id']?.toString() ??
      widget.profile['hardware_id']?.toString() ??
      'unknown';
  String get _shortId => _userId.length >= 4 ? _userId.substring(_userId.length - 4) : _userId;
  String get _nateDisplayName => 'Nate-$_shortId';

  // ─── Animations ───────────────────────────────────────────────────────────
  late AnimationController _pulseController;
  late Animation<double> _pulseAnimation;

  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2000),
    )..repeat(reverse: true);
    _pulseAnimation = Tween<double>(begin: 0.8, end: 1.2).animate(
      CurvedAnimation(parent: _pulseController, curve: Curves.easeInOut),
    );
    _checkTierAccess();
    _connectWebSocket();
    _loadWisdom();
  }

  void _checkTierAccess() {
    final plan = (widget.profile['subscription_plan'] ?? widget.profile['tier'] ?? '')
        .toString()
        .toUpperCase();
    if (plan.contains('COACH_ONLY')) {
      setState(() {
        _errorMessage = 'Community Mesh is not available for Coach-Only accounts. '
            'Upgrade to a client tier (Threshold, Inner Chamber, or Sovereign Circle) to access group sessions.';
      });
    }
  }

  bool get _canAccess =>
      !(_errorMessage != null &&
          (widget.profile['subscription_plan'] ?? '').toString().contains('COACH_ONLY'));

  void _connectWebSocket() {
    try {
      _wsChannel = WebSocketChannel.connect(Uri.parse(AppConfig.wsUrl));
      _wsSubscription = _wsChannel!.stream.listen(
        (data) {
          try {
            final msg = jsonDecode(data);
            _handleWebSocketMessage(msg as Map<String, dynamic>);
          } catch (_) {}
        },
        onError: (e) => _onWsError(e),
        onDone: () => _onWsDone(),
      );
    } catch (e) {
      debugPrint('[CommunityMesh] WebSocket connect failed: $e');
    }
  }

  void _handleWebSocketMessage(Map<String, dynamic> msg) {
    if (!mounted) return;
    switch (msg['type']) {
      case 'community_mesh_peer':
        _handlePeerDiscovery(msg);
        break;
      case 'community_mesh_wisdom':
        _handleWisdomFromPeer(msg);
        break;
      case 'community_mesh_session_update':
        _handleSessionUpdate(msg);
        break;
    }
  }

  void _handlePeerDiscovery(Map<String, dynamic> msg) {
    final peerId = msg['peer_id'] as String?;
    final displayName = msg['display_name'] as String? ?? '';
    if (peerId == null || peerId == _userId) return;
    setState(() {
      if (!_peers.any((p) => p.id == peerId)) {
        _peers.add(MeshPeer(
          id: peerId,
          displayName: displayName,
          hasOptInName: displayName.isNotEmpty,
        ));
      }
    });
  }

  void _handleWisdomFromPeer(Map<String, dynamic> msg) {
    final text = msg['text'] as String? ?? '';
    if (text.isEmpty) return;
    setState(() {
      _wisdomFeed.insert(0, WisdomInsight(
        id: const Uuid().v4(),
        text: text,
        topic: msg['topic'] as String?,
      ));
    });
  }

  void _handleSessionUpdate(Map<String, dynamic> msg) {
    final peerCount = msg['peer_count'] as int?;
    if (peerCount != null) {
      setState(() {});
    }
  }

  void _onWsError(dynamic e) => debugPrint('[CommunityMesh] WS error: $e');
  void _onWsDone() => debugPrint('[CommunityMesh] WS closed');

  void _sendCommunityMeshMessage(Map<String, dynamic> msg) {
    try {
      _wsChannel?.sink.add(jsonEncode(msg));
    } catch (e) {
      debugPrint('[CommunityMesh] Send failed: $e');
    }
  }

  Future<void> _requestLocationPermission() async {
    final status = await Permission.location.request();
    if (!mounted) return;
    if (!status.isGranted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Location permission recommended for attendance GPS tracking.'),
          backgroundColor: _Design.goldDim,
        ),
      );
    }
  }

  Future<void> _startGroupSession() async {
    if (!_canAccess) return;
    setState(() {
      _isLoading = true;
      _errorMessage = null;
      _state = CommunityMeshState.DISCOVERING;
    });

    await _requestLocationPermission();

    _sessionId = const Uuid().v4();

    // Start BLE advertising + scanning (skip on web)
    if (!kIsWeb) {
      try {
        await ble.startCommunityMeshSession(
          localName: _nateDisplayName,
          sessionId: _sessionId!,
          onPeerFound: (id, name) {
            if (mounted) {
              setState(() {
                if (!_peers.any((p) => p.id == id)) {
                  _peers.add(MeshPeer(
                    id: id,
                    displayName: name,
                    hasOptInName: name.isNotEmpty,
                  ));
                }
              });
            }
          },
        );
      } catch (e) {
        debugPrint('[CommunityMesh] BLE start failed: $e');
        setState(() {
          _errorMessage = 'BLE unavailable. Sessions will use cloud sync only.';
        });
      }
    }

    // Notify bridge
    _sendCommunityMeshMessage({
      'type': 'community_mesh_join',
      'session_id': _sessionId,
      'user_id': _userId,
      'display_name': _nateDisplayName,
      'group_name': _groupName.isEmpty ? null : _groupName,
      'topic_tags': _topicTags,
    });

    // Create session via REST API
    await _apiCreateSession();

    setState(() {
      _isLoading = false;
      _state = CommunityMeshState.FORMING;
      _sessionStartSeconds = 0;
      _durationTimer?.cancel();
      _durationTimer = Timer.periodic(const Duration(seconds: 1), (_) {
        if (mounted) setState(() => _sessionStartSeconds++);
      });
    });
  }

  Future<void> _apiCreateSession() async {
    final token = widget.profile['token'] as String?;
    final base = AppConfig.apiBaseUrl.replaceAll(RegExp(r'/api/?$'), '').replaceAll(RegExp(r'/+$'), '');
    final uri = Uri.parse('$base/api/community/sessions');
    final body = jsonEncode({
      'session_id': _sessionId,
      'group_name': _groupName.isEmpty ? null : _groupName,
      'peer_count': _peers.length,
      'topic_tags': _topicTags,
      'manager_user_id': _isManager ? _userId : null,
    });
    try {
      final resp = await http.post(
        uri,
        headers: {
          'Content-Type': 'application/json',
          if (token != null && token.isNotEmpty) 'Authorization': 'Bearer $token',
        },
        body: body,
      ).timeout(const Duration(seconds: 10));
      if (resp.statusCode >= 400) {
        debugPrint('[CommunityMesh] Create session failed: ${resp.statusCode}');
      }
    } catch (e) {
      debugPrint('[CommunityMesh] API error: $e');
    }
  }

  Future<void> _submitCheckIn() async {
    if (_sessionId == null) return;
    final token = widget.profile['token'] as String?;
    final base = AppConfig.apiBaseUrl.replaceAll(RegExp(r'/api/?$'), '').replaceAll(RegExp(r'/+$'), '');
    final uri = Uri.parse('$base/api/community/check-in');
    try {
      await http.post(
        uri,
        headers: {
          'Content-Type': 'application/json',
          if (token != null && token.isNotEmpty) 'Authorization': 'Bearer $token',
        },
        body: jsonEncode({
          'session_id': _sessionId,
          'user_id': _userId,
          'mood_valence': _moodValence,
        }),
      ).timeout(const Duration(seconds: 5));
    } catch (e) {
      debugPrint('[CommunityMesh] Check-in failed: $e');
    }
  }

  Future<void> _endSession() async {
    setState(() {
      _state = CommunityMeshState.CLOSING;
      _isLoading = true;
    });

    _durationTimer?.cancel();

    if (!kIsWeb) {
      try {
        await ble.stopCommunityMeshSession();
      } catch (_) {}
    }

    _sendCommunityMeshMessage({
      'type': 'community_mesh_leave',
      'session_id': _sessionId,
      'user_id': _userId,
    });

    if (_sessionId != null) {
      final token = widget.profile['token'] as String?;
      final base = AppConfig.apiBaseUrl.replaceAll(RegExp(r'/api/?$'), '').replaceAll(RegExp(r'/+$'), '');
      try {
        await http.post(
          Uri.parse('$base/api/community/check-out'),
          headers: {
            'Content-Type': 'application/json',
            if (token != null && token.isNotEmpty) 'Authorization': 'Bearer $token',
          },
          body: jsonEncode({'session_id': _sessionId, 'user_id': _userId}),
        ).timeout(const Duration(seconds: 5));
      } catch (_) {}
    }

    setState(() {
      _state = CommunityMeshState.IDLE;
      _isLoading = false;
      _sessionId = null;
      _peers.clear();
      _wisdomFeed.clear();
      _attendanceVerified.clear();
    });
  }

  Future<void> _loadWisdom() async {
    final token = widget.profile['token'] as String?;
    final base = AppConfig.apiBaseUrl.replaceAll(RegExp(r'/api/?$'), '').replaceAll(RegExp(r'/+$'), '');
    final uri = Uri.parse('$base/api/community/wisdom?limit=20');
    try {
      final resp = await http.get(
        uri,
        headers: {
          if (token != null && token.isNotEmpty) 'Authorization': 'Bearer $token',
        },
      ).timeout(const Duration(seconds: 10));
      if (resp.statusCode == 200 && mounted) {
        final data = jsonDecode(resp.body) as Map<String, dynamic>;
        final insights = (data['insights'] as List<dynamic>?)
            ?.map((e) {
              final m = e as Map<String, dynamic>;
              return WisdomInsight(
                id: m['id']?.toString() ?? const Uuid().v4(),
                text: m['insight_text']?.toString() ?? '',
                topic: m['topic']?.toString(),
                convergenceCount: (m['convergence_count'] as int?) ?? 1,
                createdAt: m['created_at'] != null ? DateTime.tryParse(m['created_at'].toString()) : null,
              );
            })
            .toList() ?? [];
        setState(() {
          _wisdomFeed.clear();
          _wisdomFeed.addAll(insights);
        });
      }
    } catch (e) {
      debugPrint('[CommunityMesh] Load wisdom failed: $e');
    }
  }

  void _submitWisdom(String text) {
    if (text.trim().isEmpty || _sessionId == null) return;
    final token = widget.profile['token'] as String?;
    final base = AppConfig.apiBaseUrl.replaceAll(RegExp(r'/api/?$'), '').replaceAll(RegExp(r'/+$'), '');
    http.post(
      Uri.parse('$base/api/community/wisdom'),
      headers: {
        'Content-Type': 'application/json',
        if (token != null && token.isNotEmpty) 'Authorization': 'Bearer $token',
      },
      body: jsonEncode({
        'session_id': _sessionId,
        'anonymized_wisdom': [text.trim()],
        'topic_tags': _topicTags,
        'peer_count': _peers.length + 1,
      }),
    ).timeout(const Duration(seconds: 10)).then((resp) {
      if (resp.statusCode == 200 && mounted) {
        setState(() {
          _wisdomFeed.insert(0, WisdomInsight(
            id: const Uuid().v4(),
            text: text.trim(),
            topic: _topicTags.isNotEmpty ? _topicTags.first : null,
          ));
        });
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Wisdom shared anonymously.'),
            backgroundColor: _Design.green,
          ),
        );
      }
    }).catchError((e) {
      debugPrint('[CommunityMesh] Submit wisdom failed: $e');
    });

    _sendCommunityMeshMessage({
      'type': 'community_mesh_wisdom',
      'session_id': _sessionId,
      'text': text.trim(),
      'topic': _topicTags.isNotEmpty ? _topicTags.first : null,
    });
  }

  void _toggleActive() {
    if (_state == CommunityMeshState.FORMING) {
      setState(() => _state = CommunityMeshState.ACTIVE);
      _submitCheckIn();
    }
  }

  void _toggleManager() {
    setState(() => _isManager = !_isManager);
  }

  void _verifyAttendance(String peerId) {
    setState(() {
      _attendanceVerified[peerId] = !(_attendanceVerified[peerId] ?? false);
    });
  }

  void _saveCommunitySession() {
    if (_sharedWisdom.isEmpty) return;
    final buffer = StringBuffer();
    buffer.writeln('═══ Community Mesh Session Wisdom ═══');
    buffer.writeln('Group: ${_groupName.isNotEmpty ? _groupName : "Open Session"}');
    if (_topicTags.isNotEmpty) buffer.writeln('Topics: ${_topicTags.join(", ")}');
    buffer.writeln('Peers: ${_peers.length + 1}');
    buffer.writeln('Duration: ${_formatDuration(_sessionStartSeconds)}');
    buffer.writeln('Date: ${DateTime.now().toIso8601String().split("T").first}');
    buffer.writeln('');
    for (final w in _sharedWisdom) {
      if (w.topic != null) buffer.writeln('[${w.topic}]');
      buffer.writeln(w.text);
      if (w.convergenceCount > 1) buffer.writeln('  (resonated with ${w.convergenceCount} Nates)');
      buffer.writeln('');
    }
    Clipboard.setData(ClipboardData(text: buffer.toString()));

    final token = widget.profile['token'] as String?;
    final base = AppConfig.apiBaseUrl.replaceAll(RegExp(r'/api/?$'), '').replaceAll(RegExp(r'/+$'), '');
    http.post(
      Uri.parse('$base/api/v1/vault/save-conversation'),
      headers: {
        'Content-Type': 'application/json',
        if (token != null && token.isNotEmpty) 'Authorization': 'Bearer $token',
      },
      body: jsonEncode({
        'content': buffer.toString(),
        'title': 'Community Session — ${DateTime.now().toIso8601String().split("T").first}',
        'source': 'community_mesh',
      }),
    ).timeout(const Duration(seconds: 10)).catchError((_) => http.Response('', 500));

    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Session wisdom copied & save requested'),
          backgroundColor: _Design.green,
        ),
      );
    }
  }

  String _formatDuration(int seconds) {
    final m = seconds ~/ 60;
    final s = seconds % 60;
    return '${m.toString().padLeft(2, '0')}:${s.toString().padLeft(2, '0')}';
  }

  @override
  void dispose() {
    _durationTimer?.cancel();
    if (!kIsWeb) {
      try {
        ble.stopCommunityMeshSession();
      } catch (_) {}
    }
    _wsSubscription?.cancel();
    _wsChannel?.sink.close();
    _topicController.dispose();
    _pulseController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!_canAccess) {
      return Scaffold(
        backgroundColor: _Design.bgVoid,
        appBar: AppBar(
          backgroundColor: _Design.bgChamber,
          elevation: 0,
          title: const Text('Community Mesh', style: TextStyle(color: _Design.textPrimary)),
          iconTheme: const IconThemeData(color: _Design.gold),
        ),
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(Icons.lock_outline, size: 64, color: _Design.goldDim),
                const SizedBox(height: 16),
                Text(
                  _errorMessage ?? 'Access restricted.',
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: _Design.textSecondary, fontSize: 16),
                ),
              ],
            ),
          ),
        ),
      );
    }

    return Scaffold(
      backgroundColor: _Design.bgVoid,
      appBar: AppBar(
        backgroundColor: _Design.bgChamber,
        elevation: 0,
        title: const Text(
          'Community Mesh',
          style: TextStyle(
            color: _Design.textPrimary,
            fontSize: 20,
            fontFamily: 'Cormorant Garamond',
            fontWeight: FontWeight.bold,
          ),
        ),
        iconTheme: const IconThemeData(color: _Design.gold),
        actions: [
          if (_state != CommunityMeshState.IDLE)
            Padding(
              padding: const EdgeInsets.only(right: 4),
              child: Center(
                child: Text(
                  _formatDuration(_sessionStartSeconds),
                  style: const TextStyle(color: _Design.gold, fontFamily: 'DM Sans', fontSize: 14),
                ),
              ),
            ),
          if (_sharedWisdom.isNotEmpty)
            IconButton(
              icon: const Icon(Icons.save_alt, color: _Design.goldDim, size: 22),
              tooltip: 'Save Session Wisdom',
              onPressed: _saveCommunitySession,
            ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (_errorMessage != null) _buildErrorBanner(),
            if (_state == CommunityMeshState.IDLE) ..._buildIdleContent(),
            if (_state == CommunityMeshState.DISCOVERING) _buildDiscoveringContent(),
            if (_state == CommunityMeshState.FORMING) ..._buildFormingContent(),
            if (_state == CommunityMeshState.ACTIVE) ..._buildActiveContent(),
            if (_state == CommunityMeshState.CLOSING) _buildClosingContent(),
          ],
        ),
      ),
    );
  }

  Widget _buildErrorBanner() {
    return Container(
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: _Design.red.withOpacity(0.2),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: _Design.red),
      ),
      child: Row(
        children: [
          const Icon(Icons.info_outline, color: _Design.red, size: 24),
          const SizedBox(width: 12),
          Expanded(child: Text(_errorMessage!, style: const TextStyle(color: _Design.textPrimary, fontSize: 13))),
        ],
      ),
    );
  }

  List<Widget> _buildIdleContent() {
    return [
      _buildSessionMetadataSection(),
      const SizedBox(height: 24),
      SizedBox(
        height: 56,
        child: FilledButton.icon(
          onPressed: _isLoading ? null : _startGroupSession,
          icon: _isLoading
              ? const SizedBox(
                  width: 24,
                  height: 24,
                  child: CircularProgressIndicator(strokeWidth: 2, color: _Design.gold),
                )
              : const Icon(Icons.group_add, color: _Design.bgVoid),
          label: const Text(
            'Start Group Session',
            style: TextStyle(
              color: _Design.bgVoid,
              fontFamily: 'DM Sans',
              fontWeight: FontWeight.bold,
              fontSize: 16,
            ),
          ),
          style: FilledButton.styleFrom(
            backgroundColor: _Design.gold,
            foregroundColor: _Design.bgVoid,
          ),
        ),
      ),
      const SizedBox(height: 24),
      _buildWisdomFeedSection(),
    ];
  }

  Widget _buildDiscoveringContent() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          children: [
            const CircularProgressIndicator(color: _Design.gold),
            const SizedBox(height: 20),
            Text(
              'Discovering nearby Nates…',
              style: TextStyle(color: _Design.textSecondary, fontFamily: 'DM Sans'),
            ),
          ],
        ),
      ),
    );
  }

  List<Widget> _buildFormingContent() {
    return [
      _buildSessionMetadataSection(),
      const SizedBox(height: 16),
      _buildGroupCircle(),
      const SizedBox(height: 16),
      _buildPeerDiscoveryList(),
      const SizedBox(height: 16),
      _buildCheckInPrompt(),
      const SizedBox(height: 16),
      SizedBox(
        height: 48,
        child: OutlinedButton(
          onPressed: _toggleActive,
          style: OutlinedButton.styleFrom(
            foregroundColor: _Design.gold,
            side: const BorderSide(color: _Design.gold),
          ),
          child: const Text('Continue to Active Session', style: TextStyle(fontFamily: 'DM Sans')),
        ),
      ),
      if (_isManager) ...[
        const SizedBox(height: 16),
        _buildTakeAttendanceSection(),
      ],
      const SizedBox(height: 24),
      SizedBox(
        height: 48,
        child: OutlinedButton(
          onPressed: _isLoading ? null : _endSession,
          style: OutlinedButton.styleFrom(
            foregroundColor: _Design.red,
            side: const BorderSide(color: _Design.red),
          ),
          child: const Text('End Session', style: TextStyle(fontFamily: 'DM Sans')),
        ),
      ),
    ];
  }

  List<Widget> _buildActiveContent() {
    return [
      _buildSessionMetadataSection(),
      const SizedBox(height: 16),
      _buildGroupCircle(),
      const SizedBox(height: 16),
      _buildPeerDiscoveryList(),
      const SizedBox(height: 16),
      _buildWisdomFeedSection(),
      if (_isManager) ...[
        const SizedBox(height: 16),
        _buildTakeAttendanceSection(),
      ],
      const SizedBox(height: 24),
      SizedBox(
        height: 48,
        child: OutlinedButton(
          onPressed: _isLoading ? null : _endSession,
          style: OutlinedButton.styleFrom(
            foregroundColor: _Design.red,
            side: const BorderSide(color: _Design.red),
          ),
          child: const Text('End Session', style: TextStyle(fontFamily: 'DM Sans')),
        ),
      ),
    ];
  }

  Widget _buildClosingContent() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          children: [
            const CircularProgressIndicator(color: _Design.gold),
            const SizedBox(height: 20),
            Text(
              'Ending session…',
              style: TextStyle(color: _Design.textSecondary, fontFamily: 'DM Sans'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSessionMetadataSection() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _Design.bgChamber,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _Design.goldDim.withOpacity(0.5)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Session',
            style: TextStyle(color: _Design.gold, fontFamily: 'DM Sans', fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 12),
          TextField(
            onChanged: (v) => setState(() => _groupName = v),
            decoration: InputDecoration(
              labelText: 'Group name (optional)',
              labelStyle: TextStyle(color: _Design.textSecondary),
              enabledBorder: OutlineInputBorder(
                borderSide: BorderSide(color: _Design.goldDim),
                borderRadius: BorderRadius.circular(8),
              ),
            ),
            style: const TextStyle(color: _Design.textPrimary),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _topicController,
                  onSubmitted: (v) {
                    if (v.trim().isNotEmpty) {
                      setState(() {
                        _topicTags.add(v.trim());
                        _topicController.clear();
                      });
                    }
                  },
                  decoration: InputDecoration(
                    labelText: 'Add topic tag',
                    labelStyle: TextStyle(color: _Design.textSecondary),
                    enabledBorder: OutlineInputBorder(
                      borderSide: BorderSide(color: _Design.goldDim),
                      borderRadius: BorderRadius.circular(8),
                    ),
                  ),
                  style: const TextStyle(color: _Design.textPrimary),
                ),
              ),
              IconButton(
                onPressed: () {
                  final v = _topicController.text.trim();
                  if (v.isNotEmpty) {
                    setState(() {
                      _topicTags.add(v);
                      _topicController.clear();
                    });
                  }
                },
                icon: const Icon(Icons.add, color: _Design.gold),
              ),
            ],
          ),
          if (_topicTags.isNotEmpty) ...[
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              children: _topicTags.map((t) => Chip(
                label: Text(t, style: const TextStyle(color: _Design.textPrimary, fontSize: 12)),
                deleteIcon: const Icon(Icons.close, size: 16, color: _Design.gold),
                onDeleted: () => setState(() => _topicTags.remove(t)),
                backgroundColor: _Design.bgElevated,
              )).toList(),
            ),
          ],
          if (_state != CommunityMeshState.IDLE) ...[
            const SizedBox(height: 12),
            Row(
              children: [
                Icon(Icons.people, color: _Design.gold, size: 20),
                const SizedBox(width: 8),
                Text(
                  '${_peers.length + 1} Nates connected',
                  style: TextStyle(color: _Design.textSecondary, fontFamily: 'DM Sans'),
                ),
              ],
            ),
          ],
          if (_state == CommunityMeshState.IDLE) ...[
            const SizedBox(height: 8),
            CheckboxListTile(
              value: _isManager,
              onChanged: (v) => _toggleManager(),
              title: const Text('I am the group manager', style: TextStyle(color: _Design.textPrimary, fontSize: 14)),
              activeColor: _Design.gold,
              contentPadding: EdgeInsets.zero,
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildGroupCircle() {
    final hasPeers = _peers.isNotEmpty;
    return AnimatedBuilder(
      animation: _pulseAnimation,
      builder: (context, child) {
        return Center(
          child: Container(
            width: 160,
            height: 160,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              border: Border.all(
                color: hasPeers ? _Design.gold : _Design.goldDim,
                width: hasPeers ? 4 : 2,
              ),
              boxShadow: hasPeers
                  ? [
                      BoxShadow(
                        color: _Design.gold.withOpacity(0.4),
                        blurRadius: 20,
                        spreadRadius: 2,
                      ),
                    ]
                  : null,
            ),
            child: Center(
              child: Transform.scale(
                scale: hasPeers ? _pulseAnimation.value : 1.0,
                child: Icon(
                  hasPeers ? Icons.group : Icons.person,
                  size: 64,
                  color: hasPeers ? _Design.gold : _Design.goldDim,
                ),
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _buildPeerDiscoveryList() {
    final allPeers = [MeshPeer(id: _userId, displayName: _nateDisplayName, hasOptInName: true), ..._peers];
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _Design.bgChamber,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _Design.goldDim.withOpacity(0.5)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.people_outline, color: _Design.gold, size: 20),
              const SizedBox(width: 8),
              Text(
                'Connected Nates',
                style: TextStyle(color: _Design.gold, fontFamily: 'DM Sans', fontWeight: FontWeight.bold),
              ),
            ],
          ),
          const SizedBox(height: 12),
          ...allPeers.map((p) => Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Row(
              children: [
                CircleAvatar(
                  radius: 16,
                  backgroundColor: _Design.goldDim,
                  child: Text(
                    (p.displayName.isNotEmpty ? p.displayName : 'Nate-${p.id.substring(p.id.length.clamp(0, 4))}')
                        .substring(0, 1),
                    style: const TextStyle(color: _Design.textPrimary),
                  ),
                ),
                const SizedBox(width: 12),
                Text(
                  p.displayName.isNotEmpty ? p.displayName : 'Nate-${p.id.length >= 4 ? p.id.substring(p.id.length - 4) : p.id}',
                  style: const TextStyle(color: _Design.textPrimary, fontFamily: 'DM Sans'),
                ),
                if (_attendanceVerified[p.id] == true)
                  const Padding(
                    padding: EdgeInsets.only(left: 8),
                    child: Icon(Icons.check_circle, color: _Design.green, size: 20),
                  ),
                if (p.id != _userId) ...[
                  const Spacer(),
                  SizedBox(
                    height: 28,
                    child: TextButton.icon(
                      style: TextButton.styleFrom(
                        backgroundColor: _Design.gold.withOpacity(0.15),
                        padding: const EdgeInsets.symmetric(horizontal: 10),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
                      ),
                      icon: const Icon(Icons.toll, color: _Design.gold, size: 14),
                      label: const Text('Share Tokens', style: TextStyle(color: _Design.gold, fontSize: 10, fontWeight: FontWeight.bold)),
                      onPressed: () => _showTokenShareDialog(p),
                    ),
                  ),
                ],
              ],
            ),
          )),
        ],
      ),
    );
  }

  void _showTokenShareDialog(MeshPeer peer) {
    final controller = TextEditingController(text: '10000');
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _Design.bgElevated,
        title: Row(children: [
          const Icon(Icons.toll, color: _Design.gold, size: 24),
          const SizedBox(width: 8),
          const Text('Share Tokens', style: TextStyle(color: _Design.gold, fontSize: 18)),
        ]),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Share tokens with ${peer.displayName.isNotEmpty ? peer.displayName : "this peer"}',
                style: const TextStyle(color: _Design.textSecondary, fontSize: 13)),
            const SizedBox(height: 12),
            TextField(
              controller: controller,
              keyboardType: TextInputType.number,
              style: const TextStyle(color: _Design.textPrimary),
              decoration: InputDecoration(
                labelText: 'Tokens to share',
                labelStyle: const TextStyle(color: _Design.textSecondary),
                suffixText: 'tokens',
                suffixStyle: const TextStyle(color: _Design.textSecondary, fontSize: 11),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                  borderSide: BorderSide(color: _Design.goldDim),
                ),
              ),
            ),
            const SizedBox(height: 8),
            Builder(builder: (_) {
              final tokens = int.tryParse(controller.text) ?? 10000;
              final chunks = (tokens / 10000).ceil();
              final fee = chunks * 5;
              return Text(
                'Fee: \$$fee.00 (donated to GKM 501c3)',
                style: const TextStyle(color: _Design.textSecondary, fontSize: 11),
              );
            }),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel', style: TextStyle(color: _Design.textSecondary)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: _Design.gold),
            onPressed: () {
              Navigator.pop(ctx);
              _executeTokenShare(peer, int.tryParse(controller.text) ?? 10000);
            },
            child: const Text('Share', style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold)),
          ),
        ],
      ),
    );
  }

  Future<void> _executeTokenShare(MeshPeer peer, int tokens) async {
    try {
      final username = widget.profile['username'] ?? '';
      final token = widget.profile['token'] ?? '';
      final resp = await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}/api/gkm/token-share/initiate'),
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $token',
        },
        body: jsonEncode({
          'sharer_username': username,
          'receiver_username': peer.displayName.isNotEmpty ? peer.displayName : peer.id,
          'tokens': tokens,
        }),
      );
      if (!mounted) return;
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        final nateMsg = data['nate_response'] ?? 'Tokens shared successfully!';
        showDialog(
          context: context,
          builder: (ctx) => AlertDialog(
            backgroundColor: _Design.bgElevated,
            title: const Text('Tokens Shared!', style: TextStyle(color: _Design.green)),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(nateMsg, style: const TextStyle(color: _Design.textPrimary, fontSize: 14)),
                const SizedBox(height: 12),
                Text('New balance: ${data['sharer_balance']?.toString() ?? '—'} tokens',
                    style: const TextStyle(color: _Design.gold, fontSize: 13)),
                if (data['free_month_awarded'] == true)
                  Container(
                    margin: const EdgeInsets.only(top: 12),
                    padding: const EdgeInsets.all(8),
                    decoration: BoxDecoration(
                      color: _Design.green.withOpacity(0.15),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: const Text('🎉 Free month awarded for sharing 100k+ tokens!',
                        style: TextStyle(color: _Design.green, fontSize: 12, fontWeight: FontWeight.bold)),
                  ),
              ],
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('OK', style: TextStyle(color: _Design.gold)),
              ),
            ],
          ),
        );
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Share failed: ${resp.body}'), backgroundColor: _Design.red),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error: $e'), backgroundColor: _Design.red),
        );
      }
    }
  }

  Widget _buildCheckInPrompt() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _Design.bgChamber,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _Design.cyan.withOpacity(0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.mood, color: _Design.cyan, size: 20),
              const SizedBox(width: 8),
              Text(
                'How are you right now?',
                style: TextStyle(color: _Design.cyan, fontFamily: 'DM Sans', fontWeight: FontWeight.bold),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Slider(
            value: _moodValence,
            onChanged: (v) => setState(() => _moodValence = v),
            min: 0,
            max: 1,
            divisions: 10,
            activeColor: _Design.cyan,
            inactiveColor: _Design.goldDim,
          ),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text('Low', style: TextStyle(color: _Design.textSecondary, fontSize: 12)),
              Text('High', style: TextStyle(color: _Design.textSecondary, fontSize: 12)),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildTakeAttendanceSection() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _Design.bgChamber,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _Design.purple.withOpacity(0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.assignment_turned_in, color: _Design.purple, size: 20),
              const SizedBox(width: 8),
              Text(
                'Group Manager',
                style: TextStyle(color: _Design.purple, fontFamily: 'DM Sans', fontWeight: FontWeight.bold),
              ),
            ],
          ),
          const SizedBox(height: 12),
          ..._peers.map((p) => ListTile(
            title: Text(
              p.displayName.isNotEmpty ? p.displayName : 'Nate-${p.id.length >= 4 ? p.id.substring(p.id.length - 4) : p.id}',
              style: const TextStyle(color: _Design.textPrimary, fontFamily: 'DM Sans'),
            ),
            trailing: IconButton(
              onPressed: () => _verifyAttendance(p.id),
              icon: Icon(
                _attendanceVerified[p.id] == true ? Icons.check_circle : Icons.radio_button_unchecked,
                color: _attendanceVerified[p.id] == true ? _Design.green : _Design.goldDim,
              ),
            ),
          )),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: () {
                Navigator.of(context).push(
                  MaterialPageRoute(
                    builder: (ctx) => AttendanceExportScreen(
                      profile: widget.profile,
                      sessionId: _sessionId ?? '',
                      peers: _peers,
                      attendanceVerified: _attendanceVerified,
                      groupName: _groupName,
                    ),
                  ),
                );
              },
              icon: const Icon(Icons.file_download, color: _Design.purple),
              label: const Text('Export Attendance', style: TextStyle(color: _Design.purple, fontFamily: 'DM Sans')),
              style: OutlinedButton.styleFrom(side: const BorderSide(color: _Design.purple)),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildWisdomFeedSection() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _Design.bgChamber,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _Design.goldDim.withOpacity(0.5)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.auto_awesome, color: _Design.goldBright, size: 20),
              const SizedBox(width: 8),
              Text(
                'Group Wisdom',
                style: TextStyle(color: _Design.goldBright, fontFamily: 'DM Sans', fontWeight: FontWeight.bold),
              ),
            ],
          ),
          const SizedBox(height: 12),
          if (_state == CommunityMeshState.ACTIVE) ...[
            TextField(
              onSubmitted: (v) {
                if (v.trim().isNotEmpty) {
                  _submitWisdom(v);
                }
              },
              decoration: InputDecoration(
                hintText: 'Share an anonymized insight…',
                hintStyle: TextStyle(color: _Design.textSecondary),
                enabledBorder: OutlineInputBorder(
                  borderSide: BorderSide(color: _Design.goldDim),
                  borderRadius: BorderRadius.circular(8),
                ),
              ),
              style: const TextStyle(color: _Design.textPrimary),
            ),
            const SizedBox(height: 12),
          ],
          SizedBox(
            height: 200,
            child: ListView.builder(
              itemCount: _wisdomFeed.length,
              itemBuilder: (context, i) {
                final w = _wisdomFeed[i];
                return Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: _Design.bgElevated,
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: _Design.goldDim.withOpacity(0.3)),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        if (w.topic != null)
                          Padding(
                            padding: const EdgeInsets.only(bottom: 4),
                            child: Text(
                              w.topic!,
                              style: TextStyle(color: _Design.gold, fontSize: 11),
                            ),
                          ),
                        SelectableText(
                          w.text,
                          style: const TextStyle(color: _Design.textPrimary, fontSize: 14, fontFamily: 'DM Sans'),
                        ),
                        if (w.convergenceCount > 1)
                          Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: Text(
                              '×${w.convergenceCount}',
                              style: TextStyle(color: _Design.textSecondary, fontSize: 11),
                            ),
                          ),
                      ],
                    ),
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

// =============================================================================
// ATTENDANCE EXPORT SCREEN
// =============================================================================
class AttendanceExportScreen extends StatelessWidget {
  final Map<String, dynamic> profile;
  final String sessionId;
  final List<MeshPeer> peers;
  final Map<String, bool> attendanceVerified;
  final String groupName;

  const AttendanceExportScreen({
    super.key,
    required this.profile,
    required this.sessionId,
    required this.peers,
    required this.attendanceVerified,
    required this.groupName,
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _Design.bgVoid,
      appBar: AppBar(
        backgroundColor: _Design.bgChamber,
        elevation: 0,
        title: const Text('Export Attendance', style: TextStyle(color: _Design.textPrimary)),
        iconTheme: const IconThemeData(color: _Design.gold),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: _Design.bgChamber,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: _Design.goldDim),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Session',
                    style: TextStyle(color: _Design.gold, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 8),
                  Text('Group: ${groupName.isEmpty ? "—" : groupName}', style: TextStyle(color: _Design.textSecondary)),
                  Text('Session ID: ${sessionId.substring(0, sessionId.length.clamp(0, 8))}…', style: TextStyle(color: _Design.textSecondary, fontSize: 12)),
                ],
              ),
            ),
            const SizedBox(height: 20),
            ...peers.map((p) => ListTile(
              leading: Icon(
                attendanceVerified[p.id] == true ? Icons.check_circle : Icons.radio_button_unchecked,
                color: attendanceVerified[p.id] == true ? _Design.green : _Design.goldDim,
              ),
              title: Text(
                p.displayName.isNotEmpty ? p.displayName : 'Nate-${p.id.length >= 4 ? p.id.substring(p.id.length - 4) : p.id}',
                style: const TextStyle(color: _Design.textPrimary),
              ),
            )),
            const SizedBox(height: 24),
            SizedBox(
              height: 48,
              child: FilledButton.icon(
                onPressed: () => _exportCsv(context),
                icon: const Icon(Icons.file_download),
                label: const Text('Download CSV'),
                style: FilledButton.styleFrom(backgroundColor: _Design.gold, foregroundColor: _Design.bgVoid),
              ),
            ),
            const SizedBox(height: 12),
            SizedBox(
              height: 48,
              child: OutlinedButton.icon(
                onPressed: () => _emailAttendance(context),
                icon: const Icon(Icons.email),
                label: const Text('Email Records'),
                style: OutlinedButton.styleFrom(foregroundColor: _Design.gold, side: const BorderSide(color: _Design.gold)),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _exportCsv(BuildContext context) async {
    final token = profile['token'] as String?;
    final userId = profile['user_id']?.toString() ?? profile['hardware_id']?.toString() ?? 'unknown';
    final base = AppConfig.apiBaseUrl.replaceAll(RegExp(r'/api/?$'), '').replaceAll(RegExp(r'/+$'), '');
    final uri = Uri.parse('$base/api/community/attendance/$userId?format=csv');
    try {
      final resp = await http.get(
        uri,
        headers: {if (token != null && token.isNotEmpty) 'Authorization': 'Bearer $token'},
      );
      if (resp.statusCode == 200 && context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('CSV export triggered. Check downloads.')));
      }
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Export failed: $e')));
      }
    }
  }

  Future<void> _emailAttendance(BuildContext context) async {
    // Requires recipient email input - show dialog
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _Design.bgElevated,
        title: const Text('Email Attendance', style: TextStyle(color: _Design.textPrimary)),
        content: const Text(
          'Use the Sovereign Command dashboard or request records via support@sovereignsanctuary.net.',
          style: TextStyle(color: _Design.textSecondary),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('OK', style: TextStyle(color: _Design.gold))),
        ],
      ),
    );
  }
}
