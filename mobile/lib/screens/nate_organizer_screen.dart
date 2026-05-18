// =============================================================================
// NATE ORGANIZER — AI-Guided Content Organization (Sovereign Circle)
//
// Split-view: outline panel (top/left) + Nate chat (bottom/right)
// Voice-first, accessible, ADHD-supportive design
// =============================================================================

import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';
import '../config/app_config.dart';
import 'vault_browser_screen.dart';

// ─── Design Tokens ───────────────────────────────────────────────────────────

class _OD {
  static const bgVoid = Color(0xFF050505);
  static const bgChamber = Color(0xFF0A0A0A);
  static const bgElevated = Color(0xFF111111);
  static const gold = Color(0xFFC9A962);
  static const goldBright = Color(0xFFE8D5A3);
  static const goldDim = Color(0xFF8B7355);
  static const cyan = Color(0xFF4ECDC4);
  static const purple = Color(0xFF9D4EDD);
  static const green = Color(0xFF00FF88);
  static const red = Color(0xFFEF4444);
  static const textPrimary = Color(0xFFFFFFFF);
  static const textSecondary = Color(0xFF888888);
  static const textMuted = Color(0xFF555555);
  static const border = Color(0xFF252525);

  static Color themeColor(String theme) {
    switch (theme) {
      case 'personal': return cyan;
      case 'family': return purple;
      case 'health': return green;
      case 'work': return const Color(0xFFFF9500);
      case 'relationships': return const Color(0xFFFF6B9D);
      case 'emotions': return red;
      case 'memories': return gold;
      case 'goals': return const Color(0xFF00D4FF);
      default: return textMuted;
    }
  }
}

// ─── Screen ──────────────────────────────────────────────────────────────────

class NateOrganizerScreen extends StatefulWidget {
  final Map<String, dynamic> profile;
  final String? vaultItemId;
  final String? initialContent;

  const NateOrganizerScreen({
    super.key,
    required this.profile,
    this.vaultItemId,
    this.initialContent,
  });

  @override
  State<NateOrganizerScreen> createState() => _NateOrganizerScreenState();
}

class _NateOrganizerScreenState extends State<NateOrganizerScreen> {
  // ── State ──
  WebSocketChannel? _channel;
  String? _sessionId;
  List<Map<String, dynamic>> _sections = [];
  String? _activeSectionId;
  List<_ChatMessage> _messages = [];
  Map<String, dynamic>? _progress;
  bool _loading = false;
  bool _sessionActive = false;
  String? _error;
  Timer? _startWatchdog;

  // ── Controllers ──
  final _chatController = TextEditingController();
  final _contentController = TextEditingController();
  final _chatScrollController = ScrollController();
  final _sectionScrollController = ScrollController();

  String? _resolvedToken;

  String get _userId => widget.profile['hardware_id']?.toString() ?? '';

  @override
  void initState() {
    super.initState();
    if (widget.initialContent != null) {
      _contentController.text = widget.initialContent!;
    }
    _resolveTokenAndConnect();
  }

  Future<void> _resolveTokenAndConnect() async {
    _resolvedToken = widget.profile['token']?.toString();
    if (_resolvedToken == null || _resolvedToken!.isEmpty) {
      try {
        const storage = FlutterSecureStorage(
          aOptions: AndroidOptions(encryptedSharedPreferences: true),
        );
        _resolvedToken = await storage.read(key: 'session_token');
      } catch (_) {}
    }
    if (_resolvedToken == null || _resolvedToken!.isEmpty) {
      if (mounted) {
        setState(() {
          _error = 'Session expired. Please log in again.';
        });
      }
      return;
    }
    _connect();
  }

  @override
  void dispose() {
    _startWatchdog?.cancel();
    _channel?.sink.close();
    _chatController.dispose();
    _contentController.dispose();
    _chatScrollController.dispose();
    _sectionScrollController.dispose();
    super.dispose();
  }

  // ─── WebSocket ─────────────────────────────────────────────────────────────

  bool _authConfirmed = false;
  bool _authFailed = false;
  int _reconnectAttempts = 0;
  static const int _maxReconnectAttempts = 10;

  void _connect() {
    try {
      _channel?.sink.close();
    } catch (_) {}
    _authConfirmed = false;
    final wsUrl = AppConfig.wsUrl;
    _channel = WebSocketChannel.connect(Uri.parse(wsUrl));
    _channel!.stream.listen(
      _onMessage,
      onError: (_) => _handleSocketLost('Connection lost'),
      onDone: () => _handleSocketLost('Connection lost'),
    );
  }

  void _sendAuth() {
    _channel?.sink.add(jsonEncode({
      'type': 'auth',
      'token': _resolvedToken ?? '',
      'hardware_id': _userId,
      // Separate bridge context so main app login does not evict this socket.
      'client_context': 'organizer',
    }));
  }

  void _handleSocketLost(String message) {
    if (!mounted) return;
    _authConfirmed = false;
    _startWatchdog?.cancel();
    if (_authFailed || _reconnectAttempts >= _maxReconnectAttempts) {
      setState(() {
        if (_loading && !_sessionActive) _loading = false;
        _error = _authFailed
            ? 'Authentication failed. Please log in again.'
            : 'Unable to reconnect. Please go back and try again.';
      });
      return;
    }
    setState(() {
      if (_loading && !_sessionActive) _loading = false;
      _error = '$message Reconnecting…';
    });
    final delay = Duration(
      milliseconds: (3000 * (1 << _reconnectAttempts).clamp(1, 10)).clamp(3000, 30000),
    );
    _reconnectAttempts++;
    Future.delayed(delay, _connect);
  }

  void _onMessage(dynamic raw) {
    if (!mounted) return;
    final data = jsonDecode(raw.toString()) as Map<String, dynamic>;
    final type = data['type'] as String? ?? '';

    setState(() {
      switch (type) {
        // Auth handshake responses
        case 'connected':
          if (!_authFailed) _sendAuth();
          break;

        case 'auth_success':
          _authConfirmed = true;
          _authFailed = false;
          _reconnectAttempts = 0;
          _error = null;
          // If reconnecting with an active session, try to resume it
          if (_sessionId != null && _sessionActive) {
            _channel?.sink.add(jsonEncode({
              'type': 'organize_resume',
              'session_id': _sessionId,
            }));
          }
          break;

        case 'auth_failed':
          _authFailed = true;
          _authConfirmed = false;
          _error = 'Authentication failed. Please log in again.';
          _loading = false;
          _messages.add(_ChatMessage.system('Authentication failed'));
          break;

        case 'organize_started':
        case 'organize_resumed':
          _startWatchdog?.cancel();
          _sessionId = data['session_id'] as String?;
          _sections = List<Map<String, dynamic>>.from(data['sections'] ?? []);
          _progress = data['progress'] as Map<String, dynamic>?;
          _sessionActive = true;
          _loading = false;
          if (data['nate_message'] != null) {
            _messages.add(_ChatMessage.nate(data['nate_message']));
          }
          break;

        case 'organize_response':
          if (data['sections'] != null) {
            _sections = List<Map<String, dynamic>>.from(data['sections']);
          }
          if (data['progress'] != null) {
            _progress = data['progress'] as Map<String, dynamic>?;
          }
          if (data['nate_message'] != null) {
            final hasProposal = data['proposal'] != null;
            _messages.add(_ChatMessage.nate(
              data['nate_message'],
              proposal: hasProposal ? data['proposal'] : null,
              rewritePreview: data['rewrite_preview'] as String?,
            ));
          }
          break;

        case 'organize_saved':
          if (data['nate_message'] != null) {
            _messages.add(_ChatMessage.nate(data['nate_message']));
          }
          _messages.add(_ChatMessage.system(
            data['save_mode'] == 'overwrite' ? 'Saved (updated original)' : 'Saved as new document',
          ));
          break;

        case 'error':
          _startWatchdog?.cancel();
          _loading = false;
          _error = data['message'] as String?;
          _messages.add(_ChatMessage.system('Error: ${data['message']}'));
          break;
      }
    });

    _scrollChatToBottom();
  }

  void _scrollChatToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_chatScrollController.hasClients) {
        _chatScrollController.animateTo(
          _chatScrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  // ─── Actions ───────────────────────────────────────────────────────────────

  void _startOrganizing() {
    final content = _contentController.text.trim();
    if (content.isEmpty) {
      setState(() => _error = 'Add some content first, then tap Start.');
      return;
    }
    if (!_authConfirmed) {
      setState(() => _error = 'Still connecting — try again in a moment.');
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    _startWatchdog?.cancel();
    _startWatchdog = Timer(const Duration(seconds: 60), () {
      if (!mounted) return;
      if (_loading) {
        setState(() {
          _loading = false;
          _error = 'Start timed out. Tap Start Organizing to retry.';
        });
      }
    });
    if (!_send({
      'type': 'organize_start',
      'content': content,
      'vault_item_id': widget.vaultItemId,
    })) {
      _startWatchdog?.cancel();
      setState(() => _loading = false);
    }
  }

  void _sendChat() {
    final text = _chatController.text.trim();
    if (text.isEmpty || _sessionId == null) return;
    setState(() {
      _messages.add(_ChatMessage.user(text));
    });
    _send({'type': 'organize_message', 'session_id': _sessionId, 'text': text});
    _chatController.clear();
    _scrollChatToBottom();
  }

  void _confirmProposal() {
    if (_sessionId == null) return;
    _send({'type': 'organize_confirm', 'session_id': _sessionId});
  }

  void _rejectProposal() {
    if (_sessionId == null) return;
    _send({'type': 'organize_reject', 'session_id': _sessionId});
  }

  void _undo() {
    if (_sessionId == null) return;
    _send({'type': 'organize_undo', 'session_id': _sessionId});
  }

  void _save(String mode) {
    if (_sessionId == null) return;
    _send({'type': 'organize_save', 'session_id': _sessionId, 'save_mode': mode});
  }

  void _selectSection(String sectionId) {
    setState(() => _activeSectionId = sectionId);
    final section = _sections.firstWhere((s) => s['id'] == sectionId, orElse: () => {});
    if (section.isNotEmpty && _sessionId != null) {
      _send({
        'type': 'organize_message',
        'session_id': _sessionId,
        'text': 'Read the section "${section['label'] ?? sectionId}"',
      });
    }
  }

  void _loadFromVault() async {
    try {
      final result = await Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => VaultBrowserScreen(
            profile: widget.profile,
            selectMode: true,
          ),
        ),
      );
      if (result != null && result is String && result.isNotEmpty && mounted) {
        final existing = _contentController.text.trim();
        setState(() {
          _contentController.text = existing.isEmpty
              ? result
              : '$existing\n\n$result';
        });
      }
    } catch (_) {}
  }

  bool _send(Map<String, dynamic> msg) {
    if (!_authConfirmed) {
      setState(() => _error = 'Still connecting — try again in a moment.');
      return false;
    }
    final ch = _channel;
    if (ch == null) {
      setState(() => _error = 'Not connected. Reconnecting…');
      _connect();
      return false;
    }
    try {
      ch.sink.add(jsonEncode(msg));
      return true;
    } catch (_) {
      _authConfirmed = false;
      setState(() => _error = 'Send failed. Reconnecting…');
      _connect();
      return false;
    }
  }

  // ─── Build ─────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _OD.bgVoid,
      appBar: _buildAppBar(),
      body: _sessionActive ? _buildSplitView() : _buildStartScreen(),
    );
  }

  PreferredSizeWidget _buildAppBar() {
    return AppBar(
      backgroundColor: const Color(0xFF12120A),
      elevation: 0,
      leading: IconButton(
        icon: const Icon(Icons.arrow_back, color: _OD.textSecondary),
        onPressed: () => Navigator.pop(context),
        tooltip: 'Back',
      ),
      title: Row(children: [
        Container(
          width: 32, height: 32,
          decoration: BoxDecoration(
            gradient: const LinearGradient(colors: [_OD.gold, Color(0xFFD4A853)]),
            borderRadius: BorderRadius.circular(8),
          ),
          child: const Center(child: Text('📝', style: TextStyle(fontSize: 16))),
        ),
        const SizedBox(width: 10),
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('NATE ORGANIZER', style: TextStyle(
            fontSize: 14, fontWeight: FontWeight.w700, color: _OD.gold, letterSpacing: 2,
          )),
          Text(
            _progress != null ? _progress!['progress_text'] ?? '' : 'AI-Guided Organization',
            style: const TextStyle(fontSize: 10, color: _OD.textSecondary),
          ),
        ]),
      ]),
      actions: _sessionActive ? [
        IconButton(
          icon: const Icon(Icons.undo, color: _OD.textSecondary, size: 20),
          onPressed: _undo,
          tooltip: 'Undo',
        ),
        IconButton(
          icon: const Icon(Icons.save, color: _OD.gold, size: 20),
          onPressed: () => _showSaveDialog(),
          tooltip: 'Save',
        ),
        const SizedBox(width: 8),
      ] : [],
    );
  }

  // ─── Start Screen ──────────────────────────────────────────────────────────

  Widget _buildStartScreen() {
    if (_loading) {
      return Center(child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const CircularProgressIndicator(color: _OD.gold),
          const SizedBox(height: 16),
          Text('Analyzing your content...', style: TextStyle(
            fontSize: 16, fontWeight: FontWeight.w700, color: _OD.goldBright,
          )),
          const SizedBox(height: 8),
          const Text('Nate is reading and identifying sections.', style: TextStyle(
            fontSize: 13, color: _OD.textSecondary,
          )),
        ],
      ));
    }

    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        children: [
          const SizedBox(height: 40),
          const Text('📝', style: TextStyle(fontSize: 48)),
          const SizedBox(height: 16),
          Text('Organize with Nate', style: TextStyle(
            fontSize: 22, fontWeight: FontWeight.w700, color: _OD.goldBright,
            fontFamily: 'Cormorant Garamond',
          )),
          const SizedBox(height: 8),
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 20),
            child: Text(
              'Paste or type your content below. Nate will help you organize it through '
              'conversation — move, merge, split, or rewrite sections using voice or text.',
              style: TextStyle(fontSize: 13, color: _OD.textSecondary, height: 1.6),
              textAlign: TextAlign.center,
            ),
          ),
          const SizedBox(height: 24),
          Container(
            constraints: const BoxConstraints(maxWidth: 500),
            child: TextField(
              controller: _contentController,
              maxLines: 8,
              style: const TextStyle(color: _OD.textPrimary, fontSize: 13),
              decoration: InputDecoration(
                hintText: 'Paste your journal, notes, or writing here...',
                hintStyle: const TextStyle(color: _OD.textMuted),
                filled: true,
                fillColor: _OD.bgElevated,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: const BorderSide(color: _OD.border),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: const BorderSide(color: _OD.gold),
                ),
              ),
            ),
          ),
          const SizedBox(height: 16),
          Row(mainAxisAlignment: MainAxisAlignment.center, children: [
            ElevatedButton.icon(
              onPressed: _startOrganizing,
              icon: const Text('✨', style: TextStyle(fontSize: 16)),
              label: const Text('Start Organizing', style: TextStyle(
                fontSize: 14, fontWeight: FontWeight.w600,
              )),
              style: ElevatedButton.styleFrom(
                backgroundColor: _OD.gold,
                foregroundColor: _OD.bgVoid,
                padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 14),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
              ),
            ),
            const SizedBox(width: 12),
            OutlinedButton.icon(
              onPressed: _loadFromVault,
              icon: const Icon(Icons.folder_open, size: 18),
              label: const Text('Load from Vault', style: TextStyle(
                fontSize: 14, fontWeight: FontWeight.w600,
              )),
              style: OutlinedButton.styleFrom(
                foregroundColor: _OD.cyan,
                side: const BorderSide(color: _OD.cyan),
                padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
              ),
            ),
          ]),
          if (_error != null) ...[
            const SizedBox(height: 16),
            Text(_error!, style: const TextStyle(color: _OD.red, fontSize: 12)),
          ],
        ],
      ),
    );
  }

  // ─── Split View ────────────────────────────────────────────────────────────

  Widget _buildSplitView() {
    return LayoutBuilder(builder: (context, constraints) {
      final isLandscape = constraints.maxWidth > 700;
      if (isLandscape) {
        return Row(children: [
          Expanded(flex: 55, child: _buildOutlinePanel()),
          Container(width: 1, color: _OD.border),
          Expanded(flex: 45, child: _buildChatPanel()),
        ]);
      } else {
        // Portrait: stacked (outline top, chat bottom)
        return Column(children: [
          Expanded(child: _buildOutlinePanel()),
          Container(height: 1, color: _OD.border),
          Expanded(child: _buildChatPanel()),
        ]);
      }
    });
  }

  // ─── Outline Panel ─────────────────────────────────────────────────────────

  Widget _buildOutlinePanel() {
    final total = _sections.length;
    final organized = _sections.where((s) => s['organized'] == true).length;
    final pct = total > 0 ? (organized / total * 100).round() : 0;

    return Container(
      color: _OD.bgVoid,
      child: Column(children: [
        // Header
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          decoration: const BoxDecoration(
            border: Border(bottom: BorderSide(color: _OD.border)),
          ),
          child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
            const Text('Document Outline', style: TextStyle(
              fontSize: 14, fontWeight: FontWeight.w700, color: _OD.goldBright,
            )),
            Text('$total section${total != 1 ? 's' : ''}', style: const TextStyle(
              fontSize: 11, color: _OD.textSecondary,
            )),
          ]),
        ),
        // Progress bar
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          child: Column(children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(3),
              child: LinearProgressIndicator(
                value: total > 0 ? organized / total : 0,
                backgroundColor: _OD.bgElevated,
                valueColor: const AlwaysStoppedAnimation<Color>(_OD.gold),
                minHeight: 5,
              ),
            ),
            const SizedBox(height: 4),
            Align(
              alignment: Alignment.centerRight,
              child: Text('$pct% organized', style: const TextStyle(
                fontSize: 10, color: _OD.textMuted,
              )),
            ),
          ]),
        ),
        // Sections list
        Expanded(
          child: ListView.builder(
            controller: _sectionScrollController,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
            itemCount: _sections.length,
            itemBuilder: (ctx, i) => _buildSectionCard(_sections[i], i),
          ),
        ),
      ]),
    );
  }

  Widget _buildSectionCard(Map<String, dynamic> section, int index) {
    final id = section['id'] as String? ?? '';
    final label = section['label'] as String? ?? 'Untitled';
    final summary = section['summary'] as String? ?? '';
    final theme = section['theme'] as String? ?? 'other';
    final isOrganized = section['organized'] == true;
    final isActive = id == _activeSectionId;
    final preview = (section['content'] as String? ?? '').characters.take(120).toString();

    return Semantics(
      label: 'Section ${index + 1}: $label',
      button: true,
      child: GestureDetector(
        onTap: () => _selectSection(id),
        child: Container(
          margin: const EdgeInsets.only(bottom: 8),
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: isActive ? _OD.bgElevated : _OD.bgChamber,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(
              color: isActive ? _OD.gold : _OD.border,
              width: isActive ? 1.5 : 1,
            ),
            // Left accent for organized sections
            boxShadow: isActive ? [
              BoxShadow(color: _OD.gold.withOpacity(0.1), blurRadius: 12),
            ] : null,
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              // Theme dot
              Container(
                width: 8, height: 8,
                decoration: BoxDecoration(
                  color: _OD.themeColor(theme),
                  shape: BoxShape.circle,
                ),
              ),
              const SizedBox(width: 8),
              Expanded(child: Text(label, style: TextStyle(
                fontSize: 13, fontWeight: FontWeight.w600,
                color: isActive ? _OD.goldBright : _OD.textPrimary,
              ))),
              if (isOrganized) const Icon(Icons.check_circle, color: _OD.green, size: 14),
              const SizedBox(width: 4),
              Text('#${index + 1}', style: const TextStyle(
                fontSize: 10, color: _OD.textMuted, fontWeight: FontWeight.w600,
              )),
            ]),
            if (summary.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(summary, style: const TextStyle(
                fontSize: 11, color: _OD.textSecondary, height: 1.4,
              ), maxLines: 2, overflow: TextOverflow.ellipsis),
            ],
            if (isActive && preview.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(preview, style: const TextStyle(
                fontSize: 11, color: _OD.textMuted, fontStyle: FontStyle.italic, height: 1.4,
              ), maxLines: 3, overflow: TextOverflow.ellipsis),
            ],
          ]),
        ),
      ),
    );
  }

  // ─── Chat Panel ────────────────────────────────────────────────────────────

  Widget _buildChatPanel() {
    return Container(
      color: _OD.bgChamber,
      child: Column(children: [
        // Chat header
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          decoration: const BoxDecoration(
            border: Border(bottom: BorderSide(color: _OD.border)),
          ),
          child: Row(children: [
            Container(
              width: 28, height: 28,
              decoration: BoxDecoration(
                color: _OD.cyan.withOpacity(0.12),
                border: Border.all(color: _OD.cyan, width: 1),
                shape: BoxShape.circle,
              ),
              child: const Center(child: Text('🧠', style: TextStyle(fontSize: 14))),
            ),
            const SizedBox(width: 10),
            const Text('Little Nate', style: TextStyle(
              fontSize: 13, fontWeight: FontWeight.w600, color: _OD.cyan,
            )),
          ]),
        ),
        // Messages
        Expanded(
          child: ListView.builder(
            controller: _chatScrollController,
            padding: const EdgeInsets.all(16),
            itemCount: _messages.length,
            itemBuilder: (ctx, i) => _buildChatBubble(_messages[i]),
          ),
        ),
        // Input area
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: const BoxDecoration(
            border: Border(top: BorderSide(color: _OD.border)),
          ),
          child: Row(children: [
            Expanded(
              child: TextField(
                controller: _chatController,
                style: const TextStyle(color: _OD.textPrimary, fontSize: 13),
                decoration: InputDecoration(
                  hintText: 'Tell Nate what to do...',
                  hintStyle: const TextStyle(color: _OD.textMuted),
                  contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                  filled: true,
                  fillColor: _OD.bgElevated,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(10),
                    borderSide: const BorderSide(color: _OD.border),
                  ),
                  focusedBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(10),
                    borderSide: const BorderSide(color: _OD.gold),
                  ),
                ),
                onSubmitted: (_) => _sendChat(),
              ),
            ),
            const SizedBox(width: 8),
            // Send button — min 48x48 for accessibility
            SizedBox(
              width: 48, height: 48,
              child: ElevatedButton(
                onPressed: _sendChat,
                style: ElevatedButton.styleFrom(
                  backgroundColor: _OD.cyan,
                  shape: const CircleBorder(),
                  padding: EdgeInsets.zero,
                ),
                child: const Icon(Icons.send, color: _OD.bgVoid, size: 18),
              ),
            ),
          ]),
        ),
      ]),
    );
  }

  Widget _buildChatBubble(_ChatMessage msg) {
    if (msg.type == _ChatType.system) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Center(child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          decoration: BoxDecoration(
            color: _OD.purple.withOpacity(0.12),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: _OD.purple.withOpacity(0.3)),
          ),
          child: Text(msg.text, style: const TextStyle(
            fontSize: 11, color: Color(0xFFC9A0FF),
          ), textAlign: TextAlign.center),
        )),
      );
    }

    final isNate = msg.type == _ChatType.nate;
    return Align(
      alignment: isNate ? Alignment.centerLeft : Alignment.centerRight,
      child: Container(
        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.75),
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: isNate ? _OD.bgElevated : _OD.gold.withOpacity(0.15),
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(12),
            topRight: const Radius.circular(12),
            bottomLeft: Radius.circular(isNate ? 4 : 12),
            bottomRight: Radius.circular(isNate ? 12 : 4),
          ),
          border: Border.all(color: isNate ? _OD.border : _OD.gold.withOpacity(0.3)),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(
            isNate ? 'LITTLE NATE' : 'YOU',
            style: TextStyle(
              fontSize: 9, color: _OD.textMuted,
              fontWeight: FontWeight.w600, letterSpacing: 1,
            ),
          ),
          const SizedBox(height: 4),
          SelectableText(msg.text, style: TextStyle(
            fontSize: 13, color: isNate ? _OD.textPrimary : _OD.goldBright,
          )),
          // Proposal actions
          if (msg.proposal != null) ...[
            const SizedBox(height: 10),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: _OD.bgVoid,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: _OD.cyan.withOpacity(0.3)),
              ),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('Proposed Change', style: TextStyle(
                  fontSize: 11, color: _OD.cyan, fontWeight: FontWeight.w600,
                )),
                if (msg.rewritePreview != null) ...[
                  const SizedBox(height: 6),
                  Text(
                    msg.rewritePreview!.length > 200
                        ? '${msg.rewritePreview!.substring(0, 200)}...'
                        : msg.rewritePreview!,
                    style: const TextStyle(fontSize: 11, color: _OD.textSecondary, fontStyle: FontStyle.italic),
                  ),
                ],
                const SizedBox(height: 10),
                Row(children: [
                  // Min 48x48 touch targets
                  SizedBox(
                    height: 40,
                    child: ElevatedButton.icon(
                      onPressed: _confirmProposal,
                      icon: const Icon(Icons.check, size: 14),
                      label: const Text('Yes', style: TextStyle(fontSize: 12)),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: _OD.green,
                        foregroundColor: _OD.bgVoid,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  SizedBox(
                    height: 40,
                    child: OutlinedButton.icon(
                      onPressed: _rejectProposal,
                      icon: const Icon(Icons.close, size: 14),
                      label: const Text('No', style: TextStyle(fontSize: 12)),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: _OD.red,
                        side: const BorderSide(color: _OD.red),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                      ),
                    ),
                  ),
                ]),
              ]),
            ),
          ],
        ]),
      ),
    );
  }

  // ─── Save Dialog ───────────────────────────────────────────────────────────

  void _showSaveDialog() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _OD.bgElevated,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        title: const Text('Save Document', style: TextStyle(color: _OD.goldBright, fontSize: 16)),
        content: const Text(
          'How would you like to save?',
          style: TextStyle(color: _OD.textSecondary, fontSize: 13),
        ),
        actions: [
          TextButton(
            onPressed: () { Navigator.pop(ctx); _save('overwrite'); },
            child: const Text('Update Original', style: TextStyle(color: _OD.gold)),
          ),
          ElevatedButton(
            onPressed: () { Navigator.pop(ctx); _save('new_item'); },
            style: ElevatedButton.styleFrom(
              backgroundColor: _OD.gold, foregroundColor: _OD.bgVoid,
            ),
            child: const Text('Save as New'),
          ),
        ],
      ),
    );
  }
}

// ─── Chat Message Model ──────────────────────────────────────────────────────

enum _ChatType { nate, user, system }

class _ChatMessage {
  final _ChatType type;
  final String text;
  final Map<String, dynamic>? proposal;
  final String? rewritePreview;

  _ChatMessage({required this.type, required this.text, this.proposal, this.rewritePreview});

  factory _ChatMessage.nate(String text, {Map<String, dynamic>? proposal, String? rewritePreview}) =>
      _ChatMessage(type: _ChatType.nate, text: text, proposal: proposal, rewritePreview: rewritePreview);

  factory _ChatMessage.user(String text) =>
      _ChatMessage(type: _ChatType.user, text: text);

  factory _ChatMessage.system(String text) =>
      _ChatMessage(type: _ChatType.system, text: text);
}

