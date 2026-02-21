// =============================================================================
// MEMORY SEARCH SCREEN — Search Past Conversations with Little Nate
// =============================================================================

import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'dart:convert';
import 'dart:async';
import '../config/app_config.dart';

// =============================================================================
// DESIGN TOKENS
// =============================================================================
class _Design {
  static const bgVoid = Color(0xFF050505);
  static const bgChamber = Color(0xFF0A0A0A);
  static const bgElevated = Color(0xFF111111);
  static const bgSelected = Color(0xFF1A1510);
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
}

// =============================================================================
// MEMORY SEARCH SCREEN
// =============================================================================
class SecureSearchScreen extends StatefulWidget {
  final Map<String, dynamic> profile;
  final WebSocketChannel? socket;
  final String? prefillQuery;

  const SecureSearchScreen({
    super.key,
    required this.profile,
    this.socket,
    this.prefillQuery,
  });

  @override
  State<SecureSearchScreen> createState() => _SecureSearchScreenState();
}

class _SecureSearchScreenState extends State<SecureSearchScreen> {
  final TextEditingController _searchController = TextEditingController();
  WebSocketChannel? _socket;
  StreamSubscription? _socketSub;

  bool _authenticated = false;
  bool _authenticating = true;
  bool _isSearching = false;
  bool _isPushing = false;
  List<Map<String, dynamic>> _results = [];
  int _totalMatches = 0;
  String? _errorMessage;
  int? _expandedIndex;
  final Set<int> _selectedIndices = {};

  @override
  void initState() {
    super.initState();
    if (widget.prefillQuery != null && widget.prefillQuery!.isNotEmpty) {
      _searchController.text = widget.prefillQuery!;
    }
    _connectAndAuth();
  }

  Future<void> _connectAndAuth() async {
    try {
      _socket = WebSocketChannel.connect(Uri.parse(AppConfig.wsUrl));
      _socketSub = _socket!.stream.listen(
        (message) {
          try {
            _handleMessage(jsonDecode(message));
          } catch (_) {}
        },
        onError: (_) {
          if (mounted) setState(() { _errorMessage = 'Connection lost.'; _authenticating = false; });
        },
        onDone: () {
          if (mounted) setState(() { _authenticated = false; });
        },
      );

      final hardwareId = widget.profile['hardware_id'] ?? '';
      if (hardwareId.toString().isEmpty) {
        setState(() { _errorMessage = 'Missing identity.'; _authenticating = false; });
        return;
      }

      const storage = FlutterSecureStorage(
        aOptions: AndroidOptions(encryptedSharedPreferences: true),
      );
      final token = await storage.read(key: 'session_token');
      if (token == null || token.isEmpty) {
        setState(() { _errorMessage = 'Session expired. Please log out and back in.'; _authenticating = false; });
        return;
      }

      _socket!.sink.add(jsonEncode({
        'type': 'auth',
        'hardware_id': hardwareId,
        'token': token,
      }));
    } catch (e) {
      if (mounted) setState(() { _errorMessage = 'Failed to connect: $e'; _authenticating = false; });
    }
  }

  void _handleMessage(Map<String, dynamic> data) {
    if (!mounted) return;
    final type = data['type']?.toString() ?? '';

    switch (type) {
      case 'auth_success':
      case 'login_success':
        setState(() { _authenticated = true; _authenticating = false; _errorMessage = null; });
        if (widget.prefillQuery != null && widget.prefillQuery!.isNotEmpty) {
          Future.delayed(const Duration(milliseconds: 300), () { if (mounted) _performSearch(); });
        }
        break;

      case 'auth_failed':
      case 'login_failed':
        setState(() {
          _authenticated = false; _authenticating = false;
          _errorMessage = data['message']?.toString() ?? 'Authentication failed.';
        });
        break;

      case 'memory_search_results':
        setState(() {
          _results = (data['results'] as List?)
              ?.map((e) => Map<String, dynamic>.from(e as Map))
              .toList() ?? [];
          _totalMatches = data['total_matches'] as int? ?? _results.length;
          _isSearching = false;
          _errorMessage = null;
          _expandedIndex = null;
          _selectedIndices.clear();
        });
        break;

      case 'memory_search_error':
        setState(() {
          _errorMessage = data['error']?.toString() ?? 'Search failed';
          _isSearching = false;
        });
        break;

      case 'nate_response':
        if (_isPushing) {
          setState(() { _isPushing = false; });
          if (mounted) {
            Navigator.pop(context);
          }
        }
        break;
    }
  }

  void _performSearch() {
    final query = _searchController.text.trim();
    if (query.isEmpty || !_authenticated) return;

    setState(() {
      _isSearching = true;
      _errorMessage = null;
      _results = [];
      _expandedIndex = null;
      _selectedIndices.clear();
    });

    _socket?.sink.add(jsonEncode({
      'type': 'memory_search',
      'query': query,
      'limit': 30,
    }));
  }

  void _pushToNate() {
    if (_selectedIndices.isEmpty) return;

    final entries = _selectedIndices
        .map((i) => _results[i])
        .toList()
      ..sort((a, b) => (a['index'] as int).compareTo(b['index'] as int));

    setState(() { _isPushing = true; });

    _socket?.sink.add(jsonEncode({
      'type': 'memory_push_to_nate',
      'entries': entries,
    }));
  }

  String _formatTimestamp(String raw) {
    try {
      final dt = DateTime.parse(raw);
      final months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      final hour = dt.hour > 12 ? dt.hour - 12 : (dt.hour == 0 ? 12 : dt.hour);
      final ampm = dt.hour >= 12 ? 'pm' : 'am';
      final min = dt.minute.toString().padLeft(2, '0');
      return '${months[dt.month - 1]} ${dt.day}, ${dt.year} at $hour:$min $ampm';
    } catch (_) {
      return raw;
    }
  }

  @override
  void dispose() {
    _searchController.dispose();
    _socketSub?.cancel();
    _socket?.sink.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _Design.bgVoid,
      appBar: AppBar(
        backgroundColor: _Design.bgChamber,
        elevation: 0,
        title: const Text('Memory Search',
          style: TextStyle(color: _Design.textPrimary, fontSize: 20, fontWeight: FontWeight.bold)),
        iconTheme: const IconThemeData(color: _Design.gold),
      ),
      body: _authenticating
          ? _buildLoading('Connecting to Nate\'s memory...')
          : !_authenticated
              ? _buildError()
              : _buildBody(),
      floatingActionButton: _selectedIndices.isNotEmpty
          ? FloatingActionButton.extended(
              onPressed: _isPushing ? null : _pushToNate,
              backgroundColor: _Design.gold,
              foregroundColor: _Design.bgVoid,
              icon: _isPushing
                  ? const SizedBox(width: 18, height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2,
                        valueColor: AlwaysStoppedAnimation<Color>(_Design.bgVoid)))
                  : const Icon(Icons.send_rounded),
              label: Text(
                _isPushing
                    ? 'Sending...'
                    : 'Push to Little Nate (${_selectedIndices.length})',
                style: const TextStyle(fontWeight: FontWeight.bold),
              ),
            )
          : null,
    );
  }

  Widget _buildLoading(String message) {
    return Center(child: Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        const CircularProgressIndicator(valueColor: AlwaysStoppedAnimation<Color>(_Design.gold)),
        const SizedBox(height: 16),
        Text(message, style: const TextStyle(color: _Design.textSecondary)),
      ],
    ));
  }

  Widget _buildError() {
    return Center(child: Padding(
      padding: const EdgeInsets.all(32),
      child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
        const Icon(Icons.lock_outline, color: _Design.red, size: 48),
        const SizedBox(height: 16),
        Text(_errorMessage ?? 'Unable to connect.',
          textAlign: TextAlign.center,
          style: const TextStyle(color: _Design.textSecondary, fontSize: 16)),
        const SizedBox(height: 24),
        ElevatedButton.icon(
          onPressed: () => Navigator.pop(context),
          icon: const Icon(Icons.arrow_back), label: const Text('Go Back'),
          style: ElevatedButton.styleFrom(backgroundColor: _Design.gold, foregroundColor: _Design.bgVoid),
        ),
      ]),
    ));
  }

  Widget _buildBody() {
    return Column(children: [
      // Search bar
      Container(
        padding: const EdgeInsets.all(16),
        color: _Design.bgChamber,
        child: Column(children: [
          TextField(
            controller: _searchController,
            style: const TextStyle(color: _Design.textPrimary),
            decoration: InputDecoration(
              hintText: 'Search your conversations with Nate...',
              hintStyle: const TextStyle(color: _Design.textSecondary),
              filled: true,
              fillColor: _Design.bgElevated,
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(12),
                borderSide: const BorderSide(color: _Design.goldDim)),
              enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12),
                borderSide: const BorderSide(color: _Design.goldDim)),
              focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12),
                borderSide: const BorderSide(color: _Design.gold, width: 2)),
              prefixIcon: const Icon(Icons.psychology, color: _Design.goldDim),
              suffixIcon: IconButton(
                icon: _isSearching
                    ? const SizedBox(width: 20, height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2,
                          valueColor: AlwaysStoppedAnimation<Color>(_Design.gold)))
                    : const Icon(Icons.search, color: _Design.gold),
                onPressed: _isSearching ? null : _performSearch,
              ),
            ),
            onSubmitted: (_) => _performSearch(),
          ),
          if (_errorMessage != null) ...[
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: _Design.red.withOpacity(0.2),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: _Design.red)),
              child: Row(children: [
                const Icon(Icons.error_outline, color: _Design.red, size: 20),
                const SizedBox(width: 8),
                Expanded(child: Text(_errorMessage!,
                  style: const TextStyle(color: _Design.red, fontSize: 14))),
              ]),
            ),
          ],
          if (_totalMatches > 0) ...[
            const SizedBox(height: 8),
            Row(children: [
              Text('$_totalMatches conversation${_totalMatches == 1 ? '' : 's'} found',
                style: const TextStyle(color: _Design.textSecondary, fontSize: 13)),
              const Spacer(),
              if (_selectedIndices.isNotEmpty)
                Text('${_selectedIndices.length} selected',
                  style: const TextStyle(color: _Design.gold, fontSize: 13, fontWeight: FontWeight.w600)),
            ]),
          ],
        ]),
      ),

      // Results
      Expanded(
        child: _results.isNotEmpty
            ? ListView.builder(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 80),
                itemCount: _results.length,
                itemBuilder: (ctx, i) => _buildResultCard(i),
              )
            : _isSearching
                ? _buildLoading('Searching Nate\'s memory...')
                : Center(child: Padding(
                    padding: const EdgeInsets.all(32),
                    child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                      const Icon(Icons.psychology, color: _Design.goldDim, size: 64),
                      const SizedBox(height: 16),
                      const Text('Search Your History',
                        style: TextStyle(color: _Design.textPrimary, fontSize: 20, fontWeight: FontWeight.bold)),
                      const SizedBox(height: 8),
                      const Padding(
                        padding: EdgeInsets.symmetric(horizontal: 24),
                        child: Text(
                          'Find past conversations by topic, keyword, or phrase. '
                          'Select the moment you want to revisit and push it to Little Nate '
                          'to continue right where you left off.',
                          textAlign: TextAlign.center,
                          style: TextStyle(color: _Design.textSecondary, fontSize: 14),
                        ),
                      ),
                    ]),
                  )),
      ),
    ]);
  }

  Widget _buildResultCard(int index) {
    final result = _results[index];
    final timestamp = _formatTimestamp(result['timestamp'] as String? ?? '');
    final userPreview = result['user_preview'] as String? ?? '';
    final aiPreview = result['ai_preview'] as String? ?? '';
    final userFull = result['user_full'] as String? ?? userPreview;
    final aiFull = result['ai_full'] as String? ?? aiPreview;
    final isExpanded = _expandedIndex == index;
    final isSelected = _selectedIndices.contains(index);

    return GestureDetector(
      onTap: () {
        setState(() {
          _expandedIndex = isExpanded ? null : index;
        });
      },
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: isSelected ? _Design.bgSelected : _Design.bgElevated,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: isSelected
                ? _Design.gold.withOpacity(0.6)
                : _Design.goldDim.withOpacity(0.15),
            width: isSelected ? 1.5 : 1,
          ),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          // Header: timestamp + select checkbox
          Row(children: [
            const Icon(Icons.access_time, color: _Design.textMuted, size: 14),
            const SizedBox(width: 6),
            Expanded(child: Text(timestamp,
              style: const TextStyle(color: _Design.textMuted, fontSize: 12))),
            GestureDetector(
              onTap: () {
                setState(() {
                  if (isSelected) {
                    _selectedIndices.remove(index);
                  } else {
                    _selectedIndices.add(index);
                  }
                });
              },
              child: Container(
                width: 28, height: 28,
                decoration: BoxDecoration(
                  color: isSelected ? _Design.gold : Colors.transparent,
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(
                    color: isSelected ? _Design.gold : _Design.goldDim,
                    width: 1.5),
                ),
                child: isSelected
                    ? const Icon(Icons.check, color: _Design.bgVoid, size: 18)
                    : null,
              ),
            ),
          ]),
          const SizedBox(height: 10),

          // "You said" preview
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: _Design.cyan.withOpacity(0.15),
                borderRadius: BorderRadius.circular(4)),
              child: const Text('You', style: TextStyle(color: _Design.cyan, fontSize: 11, fontWeight: FontWeight.w600)),
            ),
            const SizedBox(width: 8),
            Expanded(child: Text(
              isExpanded ? userFull : userPreview,
              style: const TextStyle(color: _Design.textPrimary, fontSize: 14),
              maxLines: isExpanded ? null : 2,
              overflow: isExpanded ? null : TextOverflow.ellipsis,
            )),
          ]),
          const SizedBox(height: 8),

          // "Nate said" preview
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: _Design.gold.withOpacity(0.15),
                borderRadius: BorderRadius.circular(4)),
              child: const Text('Nate', style: TextStyle(color: _Design.gold, fontSize: 11, fontWeight: FontWeight.w600)),
            ),
            const SizedBox(width: 8),
            Expanded(child: Text(
              isExpanded ? aiFull : aiPreview,
              style: const TextStyle(color: _Design.textSecondary, fontSize: 14),
              maxLines: isExpanded ? null : 2,
              overflow: isExpanded ? null : TextOverflow.ellipsis,
            )),
          ]),

          // Expand indicator
          if (!isExpanded) ...[
            const SizedBox(height: 6),
            const Center(child: Icon(Icons.expand_more, color: _Design.textMuted, size: 18)),
          ] else ...[
            const SizedBox(height: 6),
            const Center(child: Icon(Icons.expand_less, color: _Design.goldDim, size: 18)),
          ],
        ]),
      ),
    );
  }
}
