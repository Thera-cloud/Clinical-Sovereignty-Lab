// =============================================================================
// MEMORY SEARCH SCREEN — Search Past Conversations with Little Nate
// =============================================================================

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
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
  final String? prefillQuery;

  const SecureSearchScreen({
    super.key,
    required this.profile,
    this.prefillQuery,
  });

  @override
  State<SecureSearchScreen> createState() => _SecureSearchScreenState();
}

class _SecureSearchScreenState extends State<SecureSearchScreen>
    with SingleTickerProviderStateMixin {
  final TextEditingController _searchController = TextEditingController();
  late TabController _tabController;

  // Search tab state
  bool _isSearching = false;
  List<Map<String, dynamic>> _results = [];
  int _totalMatches = 0;
  String? _errorMessage;
  int? _expandedIndex;
  final Set<int> _selectedIndices = {};
  String? _token;

  // Browse tab state
  bool _isBrowseLoading = false;
  List<Map<String, dynamic>> _sessions = [];
  int _totalSessions = 0;
  String? _browseError;
  int? _expandedSession;
  int? _expandedBrowseEntry;
  bool _browseLoaded = false;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
    _tabController.addListener(() {
      if (_tabController.index == 1 && !_browseLoaded) {
        _loadSessions();
      }
    });
    if (widget.prefillQuery != null && widget.prefillQuery!.isNotEmpty) {
      _searchController.text = widget.prefillQuery!;
    }
    _initToken();
  }

  Future<void> _initToken() async {
    const storage = FlutterSecureStorage(
      aOptions: AndroidOptions(encryptedSharedPreferences: true),
    );
    _token = await storage.read(key: 'session_token');
    if (widget.prefillQuery != null && widget.prefillQuery!.isNotEmpty) {
      _performSearch();
    }
  }

  // ===========================================================================
  // SEARCH TAB
  // ===========================================================================
  Future<void> _performSearch() async {
    final query = _searchController.text.trim();
    if (query.isEmpty) return;

    final hwId = (widget.profile['hardware_id'] ?? '').toString();
    if (hwId.isEmpty || _token == null) {
      setState(() { _errorMessage = 'Session expired.'; });
      return;
    }

    setState(() {
      _isSearching = true;
      _errorMessage = null;
      _results = [];
      _expandedIndex = null;
      _selectedIndices.clear();
    });

    try {
      final url = '${AppConfig.apiBaseUrl}/api/client/memory/search/$hwId?q=${Uri.encodeComponent(query)}&limit=30';
      final resp = await http.get(
        Uri.parse(url),
        headers: {'Authorization': 'Bearer $_token'},
      ).timeout(const Duration(seconds: 15));

      if (!mounted) return;
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body) as Map<String, dynamic>;
        setState(() {
          _results = (data['results'] as List?)
              ?.map((e) => Map<String, dynamic>.from(e as Map))
              .toList() ?? [];
          _totalMatches = data['total_matches'] as int? ?? _results.length;
          _isSearching = false;
          _errorMessage = null;
        });
      } else {
        setState(() { _errorMessage = 'Search failed (${resp.statusCode})'; _isSearching = false; });
      }
    } catch (e) {
      if (mounted) setState(() { _errorMessage = 'Connection error: $e'; _isSearching = false; });
    }
  }

  // ===========================================================================
  // BROWSE TAB
  // ===========================================================================
  Future<void> _loadSessions() async {
    final hwId = (widget.profile['hardware_id'] ?? '').toString();
    if (hwId.isEmpty || _token == null) {
      setState(() { _browseError = 'Session expired.'; });
      return;
    }

    setState(() { _isBrowseLoading = true; _browseError = null; });

    try {
      final url = '${AppConfig.apiBaseUrl}/api/client/memory/sessions/$hwId';
      final resp = await http.get(
        Uri.parse(url),
        headers: {'Authorization': 'Bearer $_token'},
      ).timeout(const Duration(seconds: 20));

      if (!mounted) return;
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body) as Map<String, dynamic>;
        setState(() {
          _sessions = (data['sessions'] as List?)
              ?.map((e) => Map<String, dynamic>.from(e as Map))
              .toList() ?? [];
          _totalSessions = data['total_sessions'] as int? ?? _sessions.length;
          _isBrowseLoading = false;
          _browseLoaded = true;
        });
      } else {
        setState(() { _browseError = 'Failed to load sessions (${resp.statusCode})'; _isBrowseLoading = false; });
      }
    } catch (e) {
      if (mounted) setState(() { _browseError = 'Connection error: $e'; _isBrowseLoading = false; });
    }
  }

  void _pushToNate() {
    if (_selectedIndices.isEmpty) return;
    final entries = _selectedIndices
        .map((i) => _results[i])
        .toList()
      ..sort((a, b) => (a['index'] as int).compareTo(b['index'] as int));
    Navigator.pop(context, {'push_entries': entries});
  }

  void _copySessionTranscript(String date, List<Map<String, dynamic>> entries) {
    final buf = StringBuffer();
    buf.writeln('Sovereign Sanctuary \u2014 Conversation Transcript');
    buf.writeln('Date: ${_formatDate(date)}');
    buf.writeln('\u2014' * 40);
    for (final e in entries) {
      final ts = _formatTimestamp(e['timestamp'] as String? ?? '');
      buf.writeln('\n[$ts]');
      buf.writeln('You: ${e['user'] ?? ''}');
      buf.writeln('Nate: ${e['ai'] ?? ''}');
    }
    buf.writeln('\n${'=' * 40}');
    buf.writeln('sovereignsanctuary.net');
    Clipboard.setData(ClipboardData(text: buf.toString()));
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('Transcript copied to clipboard'),
        duration: Duration(seconds: 2),
      ),
    );
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

  String _formatDate(String raw) {
    try {
      final dt = DateTime.parse(raw);
      final months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      final now = DateTime.now();
      final diff = now.difference(dt).inDays;
      if (diff == 0) return 'Today';
      if (diff == 1) return 'Yesterday';
      return '${months[dt.month - 1]} ${dt.day}, ${dt.year}';
    } catch (_) {
      return raw;
    }
  }

  @override
  void dispose() {
    _searchController.dispose();
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _Design.bgVoid,
      appBar: AppBar(
        backgroundColor: _Design.bgChamber,
        elevation: 0,
        title: const Text('Memory',
          style: TextStyle(color: _Design.textPrimary, fontSize: 20, fontWeight: FontWeight.bold)),
        iconTheme: const IconThemeData(color: _Design.gold),
        bottom: TabBar(
          controller: _tabController,
          indicatorColor: _Design.gold,
          labelColor: _Design.gold,
          unselectedLabelColor: _Design.textSecondary,
          tabs: const [
            Tab(icon: Icon(Icons.search, size: 18), text: 'Search'),
            Tab(icon: Icon(Icons.auto_stories, size: 18), text: 'Browse by Story'),
          ],
        ),
      ),
      body: TabBarView(
        controller: _tabController,
        children: [
          _buildSearchTab(),
          _buildBrowseTab(),
        ],
      ),
      floatingActionButton: _tabController.index == 0 && _selectedIndices.isNotEmpty
          ? FloatingActionButton.extended(
              onPressed: _pushToNate,
              backgroundColor: _Design.gold,
              foregroundColor: _Design.bgVoid,
              icon: const Icon(Icons.send_rounded),
              label: Text(
                'Push to Little Nate (${_selectedIndices.length})',
                style: const TextStyle(fontWeight: FontWeight.bold),
              ),
            )
          : null,
    );
  }

  // ===========================================================================
  // SEARCH TAB UI
  // ===========================================================================
  Widget _buildSearchTab() {
    return Column(children: [
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

      Expanded(
        child: _results.isNotEmpty
            ? _buildGroupedResults()
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

  Widget _buildGroupedResults() {
    final Map<String, List<int>> groups = {};
    for (var i = 0; i < _results.length; i++) {
      final sessionDate = (_results[i]['session_date'] as String?)
          ?? (_results[i]['timestamp'] as String? ?? '')
              .toString()
              .substring(0, (_results[i]['timestamp'] as String? ?? '').length >= 10 ? 10 : 0);
      final key = sessionDate.isNotEmpty ? sessionDate : 'Unknown';
      groups.putIfAbsent(key, () => []).add(i);
    }
    final sortedKeys = groups.keys.toList()..sort((a, b) => b.compareTo(a));

    return ListView.builder(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 80),
      itemCount: sortedKeys.length,
      itemBuilder: (ctx, gi) {
        final dateKey = sortedKeys[gi];
        final indices = groups[dateKey]!;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 10),
              child: Row(children: [
                const Icon(Icons.calendar_today, color: _Design.goldDim, size: 14),
                const SizedBox(width: 8),
                Text(_formatDate(dateKey),
                  style: const TextStyle(color: _Design.gold, fontSize: 14, fontWeight: FontWeight.w600)),
                const SizedBox(width: 8),
                Text('${indices.length} match${indices.length == 1 ? '' : 'es'}',
                  style: const TextStyle(color: _Design.textMuted, fontSize: 12)),
                const Spacer(),
                Container(height: 1, width: 40, color: _Design.goldDim.withOpacity(0.3)),
              ]),
            ),
            ...indices.map((i) => _buildResultCard(i)),
          ],
        );
      },
    );
  }

  // ===========================================================================
  // BROWSE TAB UI
  // ===========================================================================
  Widget _buildBrowseTab() {
    if (_isBrowseLoading) return _buildLoading('Loading your story...');
    if (_browseError != null) {
      return Center(child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
          const Icon(Icons.error_outline, color: _Design.red, size: 48),
          const SizedBox(height: 16),
          Text(_browseError!, textAlign: TextAlign.center,
            style: const TextStyle(color: _Design.textSecondary, fontSize: 16)),
          const SizedBox(height: 24),
          ElevatedButton.icon(
            onPressed: _loadSessions,
            icon: const Icon(Icons.refresh), label: const Text('Retry'),
            style: ElevatedButton.styleFrom(backgroundColor: _Design.gold, foregroundColor: _Design.bgVoid),
          ),
        ]),
      ));
    }
    if (_sessions.isEmpty) {
      return Center(child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
          const Icon(Icons.auto_stories, color: _Design.goldDim, size: 64),
          const SizedBox(height: 16),
          const Text('Your Story Begins Here',
            style: TextStyle(color: _Design.textPrimary, fontSize: 20, fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          const Text(
            'Every conversation with Little Nate becomes a chapter in your story. '
            'Start talking and your journey will appear here.',
            textAlign: TextAlign.center,
            style: TextStyle(color: _Design.textSecondary, fontSize: 14)),
        ]),
      ));
    }

    return Column(children: [
      Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        color: _Design.bgChamber,
        child: Row(children: [
          const Icon(Icons.auto_stories, color: _Design.goldDim, size: 18),
          const SizedBox(width: 8),
          Text('$_totalSessions session${_totalSessions == 1 ? '' : 's'}',
            style: const TextStyle(color: _Design.textSecondary, fontSize: 13)),
        ]),
      ),
      Expanded(
        child: ListView.builder(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
          itemCount: _sessions.length,
          itemBuilder: (ctx, i) => _buildSessionChapter(i),
        ),
      ),
    ]);
  }

  Widget _buildSessionChapter(int index) {
    final session = _sessions[index];
    final date = session['date'] as String? ?? '';
    final entryCount = session['entry_count'] as int? ?? 0;
    final preview = session['preview'] as String? ?? '';
    final entries = (session['entries'] as List?)
        ?.map((e) => Map<String, dynamic>.from(e as Map))
        .toList() ?? [];
    final isExpanded = _expandedSession == index;

    return AnimatedContainer(
      duration: const Duration(milliseconds: 200),
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(
        color: _Design.bgElevated,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: isExpanded
              ? _Design.gold.withOpacity(0.4)
              : _Design.goldDim.withOpacity(0.15),
        ),
      ),
      child: Column(children: [
        InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: () => setState(() {
            _expandedSession = isExpanded ? null : index;
            _expandedBrowseEntry = null;
          }),
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Row(children: [
              Container(
                width: 40, height: 40,
                decoration: BoxDecoration(
                  color: _Design.gold.withOpacity(0.12),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Center(child: Text(
                  '${index + 1}',
                  style: const TextStyle(color: _Design.gold, fontSize: 16, fontWeight: FontWeight.bold),
                )),
              ),
              const SizedBox(width: 12),
              Expanded(child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(_formatDate(date),
                    style: const TextStyle(color: _Design.textPrimary, fontSize: 15, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 4),
                  Text(preview,
                    maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: const TextStyle(color: _Design.textSecondary, fontSize: 13)),
                ],
              )),
              const SizedBox(width: 8),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: _Design.cyan.withOpacity(0.12),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text('$entryCount',
                  style: const TextStyle(color: _Design.cyan, fontSize: 12, fontWeight: FontWeight.w600)),
              ),
              const SizedBox(width: 4),
              Icon(isExpanded ? Icons.expand_less : Icons.expand_more,
                color: _Design.goldDim, size: 22),
            ]),
          ),
        ),
        if (isExpanded) ...[
          Container(height: 1, color: _Design.goldDim.withOpacity(0.15)),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                SizedBox(
                  height: 30,
                  child: TextButton.icon(
                    onPressed: () => _copySessionTranscript(date, entries),
                    icon: const Icon(Icons.copy_all, size: 14, color: _Design.gold),
                    label: const Text('Copy Transcript',
                      style: TextStyle(color: _Design.gold, fontSize: 11, fontWeight: FontWeight.w600)),
                  ),
                ),
              ],
            ),
          ),
          ...entries.asMap().entries.map((mapEntry) {
            final ei = mapEntry.key;
            final e = mapEntry.value;
            final ts = e['timestamp'] as String? ?? '';
            final user = e['user'] as String? ?? '';
            final ai = e['ai'] as String? ?? '';
            final isEntryExpanded = _expandedBrowseEntry == ei;

            return InkWell(
              onTap: () => setState(() {
                _expandedBrowseEntry = isEntryExpanded ? null : ei;
              }),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                decoration: BoxDecoration(
                  border: Border(
                    bottom: BorderSide(color: _Design.goldDim.withOpacity(0.08)),
                  ),
                ),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    const Icon(Icons.access_time, color: _Design.textMuted, size: 12),
                    const SizedBox(width: 4),
                    Text(_formatTimestamp(ts),
                      style: const TextStyle(color: _Design.textMuted, fontSize: 11)),
                  ]),
                  const SizedBox(height: 6),
                  Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
                      decoration: BoxDecoration(
                        color: _Design.cyan.withOpacity(0.15),
                        borderRadius: BorderRadius.circular(3)),
                      child: const Text('You', style: TextStyle(color: _Design.cyan, fontSize: 10, fontWeight: FontWeight.w600)),
                    ),
                    const SizedBox(width: 6),
                    Expanded(child: isEntryExpanded
                      ? SelectableText(user,
                          style: const TextStyle(color: _Design.textPrimary, fontSize: 13))
                      : Text(user,
                          style: const TextStyle(color: _Design.textPrimary, fontSize: 13),
                          maxLines: 2, overflow: TextOverflow.ellipsis)),
                  ]),
                  const SizedBox(height: 4),
                  Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
                      decoration: BoxDecoration(
                        color: _Design.gold.withOpacity(0.15),
                        borderRadius: BorderRadius.circular(3)),
                      child: const Text('Nate', style: TextStyle(color: _Design.gold, fontSize: 10, fontWeight: FontWeight.w600)),
                    ),
                    const SizedBox(width: 6),
                    Expanded(child: isEntryExpanded
                      ? SelectableText(ai,
                          style: const TextStyle(color: _Design.textSecondary, fontSize: 13))
                      : Text(ai,
                          style: const TextStyle(color: _Design.textSecondary, fontSize: 13),
                          maxLines: 2, overflow: TextOverflow.ellipsis)),
                  ]),
                ]),
              ),
            );
          }),
        ],
      ]),
    );
  }

  // ===========================================================================
  // SHARED WIDGETS
  // ===========================================================================
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

          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: _Design.cyan.withOpacity(0.15),
                borderRadius: BorderRadius.circular(4)),
              child: const Text('You', style: TextStyle(color: _Design.cyan, fontSize: 11, fontWeight: FontWeight.w600)),
            ),
            const SizedBox(width: 8),
            Expanded(child: isExpanded
              ? SelectableText(userFull,
                  style: const TextStyle(color: _Design.textPrimary, fontSize: 14))
              : Text(userPreview,
                  style: const TextStyle(color: _Design.textPrimary, fontSize: 14),
                  maxLines: 2, overflow: TextOverflow.ellipsis)),
          ]),
          const SizedBox(height: 8),

          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: _Design.gold.withOpacity(0.15),
                borderRadius: BorderRadius.circular(4)),
              child: const Text('Nate', style: TextStyle(color: _Design.gold, fontSize: 11, fontWeight: FontWeight.w600)),
            ),
            const SizedBox(width: 8),
            Expanded(child: isExpanded
              ? SelectableText(aiFull,
                  style: const TextStyle(color: _Design.textSecondary, fontSize: 14))
              : Text(aiPreview,
                  style: const TextStyle(color: _Design.textSecondary, fontSize: 14),
                  maxLines: 2, overflow: TextOverflow.ellipsis)),
          ]),

          if (isExpanded) ...[
            const SizedBox(height: 8),
            Row(mainAxisAlignment: MainAxisAlignment.end, children: [
              SizedBox(
                height: 32,
                child: TextButton.icon(
                  onPressed: () {
                    Clipboard.setData(ClipboardData(
                      text: 'You: $userFull\n\nNate: $aiFull',
                    ));
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('Copied to clipboard'), duration: Duration(seconds: 1)),
                    );
                  },
                  icon: const Icon(Icons.copy, size: 14, color: _Design.goldDim),
                  label: const Text('Copy', style: TextStyle(color: _Design.goldDim, fontSize: 11)),
                ),
              ),
            ]),
          ],

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
