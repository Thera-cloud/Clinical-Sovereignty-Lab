// =============================================================================
// SOVEREIGN VAULT BROWSER — B8
// Folder tree, grid/list toggle, search, pull-to-refresh, storage stats
// =============================================================================

import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:http/http.dart' as http;
import 'package:file_picker/file_picker.dart';
import 'dart:convert';
import 'dart:typed_data';
import '../io_file_stub.dart' if (dart.library.io) 'dart:io' show File;
import '../config/app_config.dart';
import '../widgets/vault_preview_window.dart';
import 'nate_organizer_screen.dart';

// Design tokens
class _VaultDesign {
  static const bgVoid = Color(0xFF050505);
  static const bgChamber = Color(0xFF0A0A0A);
  static const bgElevated = Color(0xFF111111);
  static const gold = Color(0xFFC9A962);
  static const goldBright = Color(0xFFE8D5A3);
  static const goldDim = Color(0xFF8B7355);
  static const cyan = Color(0xFF4ECDC4);
  static const purple = Color(0xFF9D4EDD);
  static const red = Color(0xFFEF4444);
  static const textPrimary = Color(0xFFFFFFFF);
  static const textSecondary = Color(0xFF888888);
  static const border = Color(0xFF252525);
}

class VaultBrowserScreen extends StatefulWidget {
  final Map<String, dynamic> profile;

  const VaultBrowserScreen({super.key, required this.profile});

  @override
  State<VaultBrowserScreen> createState() => _VaultBrowserScreenState();
}

class _VaultBrowserScreenState extends State<VaultBrowserScreen> {
  String get _userId => (widget.profile['hardware_id'] ?? widget.profile['id'] ?? '').toString();
  String get _baseUrl =>
      AppConfig.apiBaseUrl.replaceAll(RegExp(r'/api/?$'), '').replaceAll(RegExp(r'/+$'), '');

  List<Map<String, dynamic>> _folders = [];
  List<Map<String, dynamic>> _items = [];
  String? _selectedFolderId;
  bool _isGrid = false;
  bool _starredOnly = false;
  String _searchQuery = '';
  final _searchController = TextEditingController();
  bool _loading = true;
  String? _error;

  Map<String, dynamic>? _stats;

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _loadData() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      if (_searchQuery.trim().isNotEmpty) {
        await _searchItems();
      } else {
        await Future.wait([_loadFolders(), _loadItems(), _loadStats()]);
      }
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadFolders() async {
    final uri = Uri.parse('$_baseUrl/api/v1/vault/folders').replace(
      queryParameters: {'user_id': _userId},
    );
    final resp = await http.get(
      uri,
      headers: {'X-User-Id': _userId, 'Content-Type': 'application/json'},
    ).timeout(const Duration(seconds: 10));
    if (resp.statusCode >= 200 && resp.statusCode < 300) {
      final data = jsonDecode(resp.body);
      final list = data is List ? data : (data['folders'] as List? ?? []);
      setState(() {
        _folders = list.map((e) => Map<String, dynamic>.from(e as Map)).toList();
        if (_folders.isNotEmpty && _selectedFolderId == null) {
          _selectedFolderId = _folders.first['id']?.toString();
        }
      });
    } else {
      throw Exception('Failed to load folders: ${resp.statusCode}');
    }
  }

  Future<void> _loadItems() async {
    final folderId = _selectedFolderId ?? _folders.firstOrNull?['id']?.toString();
    if (folderId == null) {
      setState(() => _items = []);
      return;
    }
    final uri = Uri.parse('$_baseUrl/api/v1/vault/folders/$folderId/items').replace(
      queryParameters: {
        'user_id': _userId,
        'page': '1',
        'per_page': '50',
        'sort': 'date_desc',
      },
    );
    final resp = await http.get(
      uri,
      headers: {'X-User-Id': _userId, 'Content-Type': 'application/json'},
    ).timeout(const Duration(seconds: 10));
    if (resp.statusCode >= 200 && resp.statusCode < 300) {
      final data = jsonDecode(resp.body);
      List items = data is List ? data : (data['items'] as List? ?? []);
      if (_starredOnly) {
        items = items.where((e) => e['starred'] == true).toList();
      }
      setState(() => _items = items.map((e) => Map<String, dynamic>.from(e as Map)).toList());
    } else {
      throw Exception('Failed to load items: ${resp.statusCode}');
    }
  }

  Future<void> _searchItems() async {
    if (_searchQuery.trim().isEmpty) return;
    final uri = Uri.parse('$_baseUrl/api/v1/vault/search').replace(
      queryParameters: {
        'user_id': _userId,
        'q': _searchQuery.trim(),
        'max_results': '50',
      },
    );
    final resp = await http.get(
      uri,
      headers: {'X-User-Id': _userId, 'Content-Type': 'application/json'},
    ).timeout(const Duration(seconds: 10));
    if (resp.statusCode >= 200 && resp.statusCode < 300) {
      final data = jsonDecode(resp.body);
      List items = data is List ? data : (data['results'] as List? ?? data['items'] as List? ?? []);
      if (_starredOnly) {
        items = items.where((e) => e['starred'] == true).toList();
      }
      setState(() => _items = items.map((e) => Map<String, dynamic>.from(e as Map)).toList());
    } else {
      throw Exception('Search failed: ${resp.statusCode}');
    }
  }

  Future<void> _loadStats() async {
    final uri = Uri.parse('$_baseUrl/api/v1/vault/stats').replace(
      queryParameters: {'user_id': _userId},
    );
    final resp = await http.get(
      uri,
      headers: {'X-User-Id': _userId, 'Content-Type': 'application/json'},
    ).timeout(const Duration(seconds: 5));
    if (resp.statusCode >= 200 && resp.statusCode < 300) {
      setState(() => _stats = Map<String, dynamic>.from(jsonDecode(resp.body) as Map));
    }
  }

  String _formatBytes(int bytes) {
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} GB';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _VaultDesign.bgVoid,
      appBar: AppBar(
        backgroundColor: _VaultDesign.bgChamber,
        elevation: 0,
        title: const Text(
          'Sovereign Vault',
          style: TextStyle(
            color: _VaultDesign.textPrimary,
            fontFamily: 'Courier',
            fontSize: 18,
          ),
        ),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: _VaultDesign.gold),
          onPressed: () => Navigator.pop(context),
        ),
        actions: [
          IconButton(
            icon: Icon(
              _isGrid ? Icons.view_list : Icons.grid_view,
              color: _VaultDesign.gold,
            ),
            onPressed: () => setState(() => _isGrid = !_isGrid),
          ),
          IconButton(
            icon: Icon(
              _starredOnly ? Icons.star : Icons.star_border,
              color: _starredOnly ? _VaultDesign.gold : _VaultDesign.textSecondary,
            ),
            onPressed: () => setState(() {
              _starredOnly = !_starredOnly;
              _loadData();
            }),
          ),
        ],
      ),
      body: Column(
        children: [
          // Search bar
          Container(
            padding: const EdgeInsets.all(12),
            color: _VaultDesign.bgChamber,
            child: TextField(
              controller: _searchController,
              onSubmitted: (v) => setState(() {
                _searchQuery = v;
                _loadData();
              }),
              onChanged: (v) => setState(() => _searchQuery = v),
              style: const TextStyle(color: _VaultDesign.textPrimary),
              decoration: InputDecoration(
                hintText: 'Search vault...',
                hintStyle: const TextStyle(color: _VaultDesign.textSecondary),
                prefixIcon: const Icon(Icons.search, color: _VaultDesign.gold, size: 20),
                filled: true,
                fillColor: _VaultDesign.bgElevated,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                  borderSide: const BorderSide(color: _VaultDesign.border),
                ),
              ),
            ),
          ),
          // Folder tabs (top tabs for mobile)
          if (_folders.isNotEmpty && _searchQuery.trim().isEmpty)
            SizedBox(
              height: 44,
              child: ListView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 12),
                children: _folders.map((f) {
                  final id = f['id']?.toString();
                  final selected = id == _selectedFolderId;
                  return Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: ChoiceChip(
                      label: Text(f['name'] ?? '?', style: const TextStyle(fontSize: 12)),
                      selected: selected,
                      onSelected: (v) {
                        setState(() {
                          _selectedFolderId = id;
                          _loadItems();
                        });
                      },
                      backgroundColor: _VaultDesign.bgElevated,
                      selectedColor: _VaultDesign.gold.withOpacity(0.3),
                      labelStyle: TextStyle(
                        color: selected ? _VaultDesign.gold : _VaultDesign.textSecondary,
                      ),
                    ),
                  );
                }).toList(),
              ),
            ),
          const SizedBox(height: 8),
          // Content area
          Expanded(
            child: RefreshIndicator(
              onRefresh: _loadData,
              color: _VaultDesign.gold,
              backgroundColor: _VaultDesign.bgElevated,
              child: _buildContent(),
            ),
          ),
          // Stats bar
          _buildStatsBar(),
        ],
      ),
      floatingActionButton: FloatingActionButton(
        backgroundColor: _VaultDesign.gold,
        onPressed: () => _showUploadOptions(),
        child: const Icon(Icons.add, color: Colors.black),
      ),
    );
  }

  Widget _buildContent() {
    if (_loading && _items.isEmpty) {
      return const Center(
        child: CircularProgressIndicator(color: _VaultDesign.gold),
      );
    }
    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.error_outline, color: _VaultDesign.red, size: 48),
              const SizedBox(height: 12),
              Text(
                _error!,
                textAlign: TextAlign.center,
                style: const TextStyle(color: _VaultDesign.textSecondary, fontSize: 13),
              ),
              const SizedBox(height: 16),
              TextButton(
                onPressed: _loadData,
                child: const Text('Retry', style: TextStyle(color: _VaultDesign.gold)),
              ),
            ],
          ),
        ),
      );
    }
    if (_items.isEmpty) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.folder_open, color: _VaultDesign.goldDim.withOpacity(0.5), size: 64),
            const SizedBox(height: 12),
            Text(
              _searchQuery.isNotEmpty ? 'No results' : 'No items yet',
              style: const TextStyle(color: _VaultDesign.textSecondary),
            ),
            const SizedBox(height: 8),
            TextButton.icon(
              onPressed: _searchQuery.isNotEmpty ? null : _showUploadOptions,
              icon: const Icon(Icons.upload, color: _VaultDesign.gold, size: 18),
              label: const Text('Upload', style: TextStyle(color: _VaultDesign.gold)),
            ),
          ],
        ),
      );
    }
    return _isGrid ? _buildGrid() : _buildList();
  }

  Widget _buildGrid() {
    return GridView.builder(
      padding: const EdgeInsets.all(12),
      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: 2,
        mainAxisSpacing: 12,
        crossAxisSpacing: 12,
        childAspectRatio: 0.85,
      ),
      itemCount: _items.length,
      itemBuilder: (ctx, i) => _VaultItemCard(
        item: _items[i],
        onTap: () => _openItem(_items[i]),
        onStar: () => _toggleStar(_items[i]),
      ),
    );
  }

  Widget _buildList() {
    return ListView.builder(
      padding: const EdgeInsets.all(12),
      itemCount: _items.length,
      itemBuilder: (ctx, i) => _VaultItemTile(
        item: _items[i],
        onTap: () => _openItem(_items[i]),
        onStar: () => _toggleStar(_items[i]),
      ),
    );
  }

  Widget _buildStatsBar() {
    final totalBytes = _stats?['total_size_bytes'] ?? 0;
    final limitBytes = _stats?['limit_bytes'] ?? (5 * 1024 * 1024 * 1024); // 5 GB default
    final pct = limitBytes > 0 ? (totalBytes / limitBytes).clamp(0.0, 1.0) : 0.0;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: const BoxDecoration(
        color: _VaultDesign.bgChamber,
        border: Border(top: BorderSide(color: _VaultDesign.border)),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                '${_formatBytes(totalBytes)} / ${_formatBytes(limitBytes)}',
                style: const TextStyle(
                  color: _VaultDesign.textSecondary,
                  fontSize: 12,
                  fontFamily: 'Courier',
                ),
              ),
              Text(
                '${(pct * 100).toInt()}%',
                style: const TextStyle(
                  color: _VaultDesign.gold,
                  fontSize: 12,
                  fontFamily: 'Courier',
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: pct,
              minHeight: 6,
              backgroundColor: _VaultDesign.bgElevated,
              valueColor: AlwaysStoppedAnimation<Color>(
                pct > 0.9 ? _VaultDesign.red : _VaultDesign.gold,
              ),
            ),
          ),
        ],
      ),
    );
  }

  void _showUploadOptions() {
    showModalBottomSheet(
      context: context,
      backgroundColor: _VaultDesign.bgChamber,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                'Add to Vault',
                style: TextStyle(
                  color: _VaultDesign.gold,
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 16),
              ListTile(
                leading: const Icon(Icons.upload_file, color: _VaultDesign.gold),
                title: const Text('Upload File', style: TextStyle(color: _VaultDesign.textPrimary)),
                onTap: () {
                  Navigator.pop(ctx);
                  _pickAndUpload();
                },
              ),
              ListTile(
                leading: const Icon(Icons.transfer_within_a_station, color: _VaultDesign.purple),
                title: const Text('Transfer Crystal', style: TextStyle(color: _VaultDesign.textPrimary)),
                onTap: () {
                  Navigator.pop(ctx);
                  _showTransferCrystalFlow();
                },
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _pickAndUpload() async {
    try {
      final result = await FilePicker.platform.pickFiles(allowMultiple: false);
      if (result == null || result.files.isEmpty) return;
      final file = result.files.single;
      Uint8List? bytes = file.bytes;
      if (bytes == null && file.path != null && !kIsWeb) {
        bytes = await _readFileBytes(file.path!);
      }
      if (bytes == null) return;
      final uri = Uri.parse('$_baseUrl/api/v1/upload').replace(
        queryParameters: {'user_id': _userId},
      );
      final request = http.MultipartRequest('POST', uri);
      request.headers['X-User-Id'] = _userId;
      request.fields['user_id'] = _userId;
      request.files.add(http.MultipartFile.fromBytes(
        'file',
        bytes,
        filename: file.name,
      ));
      final streamed = await request.send().timeout(const Duration(seconds: 60));
      final resp = await http.Response.fromStream(streamed);
      if (resp.statusCode >= 200 && resp.statusCode < 300) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Upload complete'), backgroundColor: _VaultDesign.gold),
          );
          _loadData();
        }
      } else {
        throw Exception('Upload failed: ${resp.statusCode}');
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Upload failed: $e'), backgroundColor: _VaultDesign.red),
        );
      }
    }
  }

  Future<Uint8List> _readFileBytes(String path) async {
    return Uint8List.fromList(await File(path).readAsBytes());
  }

  // ─── Transfer Crystal Flow ───
  void _showTransferCrystalFlow() {
    showModalBottomSheet(
      context: context,
      backgroundColor: _VaultDesign.bgElevated,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(16))),
      builder: (ctx) => Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text('Transfer Crystal', style: TextStyle(color: _VaultDesign.gold, fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            const Text('Import your AI chat history from another platform.', style: TextStyle(color: _VaultDesign.textSecondary, fontSize: 12)),
            const SizedBox(height: 16),
            _crystalSourceTile(ctx, 'ChatGPT (OpenAI)', 'ZIP export', Icons.chat_bubble, 'chatgpt'),
            _crystalSourceTile(ctx, 'Claude (Anthropic)', 'JSON export', Icons.psychology, 'claude'),
            _crystalSourceTile(ctx, 'Gemini (Google)', 'Takeout export', Icons.auto_awesome, 'gemini'),
            _crystalSourceTile(ctx, 'Replika', 'JSON or CSV', Icons.favorite, 'replika'),
            const SizedBox(height: 8),
            ListTile(
              leading: const Icon(Icons.auto_fix_high, color: _VaultDesign.gold),
              title: const Text('Auto-Detect', style: TextStyle(color: _VaultDesign.textPrimary)),
              onTap: () { Navigator.pop(ctx); _pickAndUploadCrystal('auto'); },
            ),
          ],
        ),
      ),
    );
  }

  Widget _crystalSourceTile(BuildContext ctx, String title, String sub, IconData icon, String src) {
    return ListTile(
      leading: Icon(icon, color: _VaultDesign.gold),
      title: Text(title, style: const TextStyle(color: _VaultDesign.textPrimary)),
      subtitle: Text(sub, style: const TextStyle(color: _VaultDesign.textSecondary, fontSize: 11)),
      onTap: () { Navigator.pop(ctx); _pickAndUploadCrystal(src); },
    );
  }

  Future<void> _pickAndUploadCrystal(String source) async {
    try {
      final result = await FilePicker.platform.pickFiles(
        allowMultiple: false,
        type: FileType.custom,
        allowedExtensions: ['zip', 'json', 'csv'],
      );
      if (result == null || result.files.isEmpty) return;
      final file = result.files.single;
      Uint8List? bytes = file.bytes;
      if (bytes == null && file.path != null && !kIsWeb) {
        bytes = await _readFileBytes(file.path!);
      }
      if (bytes == null) return;

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Importing... this may take a moment'), backgroundColor: _VaultDesign.gold),
        );
      }

      final uri = Uri.parse('$_baseUrl/api/v1/vault/import');
      final request = http.MultipartRequest('POST', uri);
      request.headers['X-User-Id'] = _userId;
      request.fields['source'] = source;
      request.files.add(http.MultipartFile.fromBytes('file', bytes, filename: file.name));
      final streamed = await request.send().timeout(const Duration(seconds: 120));
      final resp = await http.Response.fromStream(streamed);

      if (!mounted) return;
      if (resp.statusCode >= 200 && resp.statusCode < 300) {
        final data = jsonDecode(resp.body);
        final crystal = data['crystal'];
        final stats = data['stats'];
        showDialog(
          context: context,
          builder: (ctx) => AlertDialog(
            backgroundColor: _VaultDesign.bgElevated,
            title: const Text('Transfer Crystal Created', style: TextStyle(color: _VaultDesign.gold)),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (stats != null) ...[
                  Text('Source: ${data['source'] ?? source}', style: const TextStyle(color: _VaultDesign.textSecondary, fontSize: 12)),
                  if (stats['conversations_imported'] != null)
                    Text('Conversations: ${stats['conversations_imported']}', style: const TextStyle(color: _VaultDesign.textSecondary, fontSize: 12)),
                  const SizedBox(height: 8),
                ],
                if (crystal != null && crystal is Map)
                  Text(crystal['summary'] ?? 'Crystal created successfully', style: const TextStyle(color: _VaultDesign.textPrimary, fontSize: 12))
                else
                  const Text('Imported into Sovereign Vault.', style: TextStyle(color: _VaultDesign.textPrimary, fontSize: 12)),
              ],
            ),
            actions: [TextButton(onPressed: () { Navigator.pop(ctx); _loadData(); }, child: const Text('Done', style: TextStyle(color: _VaultDesign.gold)))],
          ),
        );
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Import failed: ${resp.statusCode}'), backgroundColor: _VaultDesign.gold),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error: $e'), backgroundColor: _VaultDesign.gold),
        );
      }
    }
  }

  bool get _isSovereignCircle {
    final plan = (widget.profile['subscription_plan'] ?? '').toString().toUpperCase();
    return plan == 'SOVEREIGN_CIRCLE' || plan == 'TOP_TIER' || plan == 'TOP';
  }

  void _openItem(Map<String, dynamic> item) {
    showModalBottomSheet(
      context: context,
      backgroundColor: Colors.transparent,
      builder: (ctx) => VaultPreviewWindow(
        item: item,
        onOpenInVault: () => Navigator.pop(ctx),
        onAskNate: () {
          Navigator.pop(ctx);
          Navigator.pop(context, item['id']?.toString());
        },
        onStar: () {
          _toggleStar(item);
          Navigator.pop(ctx);
        },
        // Sovereign Circle: Organize with Nate
        extraActions: _isSovereignCircle ? [
          VaultExtraAction(
            icon: Icons.auto_fix_high,
            label: 'Organize with Nate',
            color: _VaultDesign.gold,
            onTap: () {
              Navigator.pop(ctx);
              Navigator.push(context, MaterialPageRoute(
                builder: (_) => NateOrganizerScreen(
                  profile: widget.profile,
                  vaultItemId: item['id']?.toString(),
                  initialContent: item['extracted_text_preview']?.toString(),
                ),
              ));
            },
          ),
        ] : null,
      ),
    );
  }

  Future<void> _toggleStar(Map<String, dynamic> item) async {
    final id = item['id']?.toString();
    if (id == null) return;
    try {
      final uri = Uri.parse('$_baseUrl/api/v1/vault/items/$id/star').replace(
        queryParameters: {'user_id': _userId},
      );
      final resp = await http.post(
        uri,
        headers: {'X-User-Id': _userId, 'Content-Type': 'application/json'},
      ).timeout(const Duration(seconds: 5));
      if (resp.statusCode >= 200 && resp.statusCode < 300) {
        setState(() {
          item['starred'] = !(item['starred'] ?? false);
        });
      }
    } catch (_) {}
  }
}

class _VaultItemCard extends StatelessWidget {
  final Map<String, dynamic> item;
  final VoidCallback onTap;
  final VoidCallback onStar;

  const _VaultItemCard({
    required this.item,
    required this.onTap,
    required this.onStar,
  });

  @override
  Widget build(BuildContext context) {
    final name = item['display_name'] ?? 'Untitled';
    final ct = (item['content_type'] ?? 'document').toString();
    final date = item['created_at'] ?? item['updated_at'] ?? '';
    final starred = item['starred'] ?? false;
    final isImage = ct.contains('image') || ct.contains('upload_image');

    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: _VaultDesign.bgElevated,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: _VaultDesign.border),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  isImage ? Icons.image : Icons.description,
                  color: _VaultDesign.gold,
                  size: 32,
                ),
                const Spacer(),
                GestureDetector(
                  onTap: onStar,
                  child: Icon(
                    starred ? Icons.star : Icons.star_border,
                    color: starred ? _VaultDesign.gold : _VaultDesign.textSecondary,
                    size: 18,
                  ),
                ),
              ],
            ),
            const Spacer(),
            Text(
              name.length > 20 ? '${name.substring(0, 20)}…' : name,
              style: const TextStyle(
                color: _VaultDesign.textPrimary,
                fontSize: 12,
                fontWeight: FontWeight.w500,
              ),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
            const SizedBox(height: 4),
            Text(
              _formatDate(date),
              style: const TextStyle(color: _VaultDesign.textSecondary, fontSize: 10),
            ),
            const SizedBox(height: 4),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: _VaultDesign.gold.withOpacity(0.2),
                borderRadius: BorderRadius.circular(4),
              ),
              child: Text(
                _contentTypeLabel(ct),
                style: const TextStyle(color: _VaultDesign.gold, fontSize: 9),
              ),
            ),
          ],
        ),
      ),
    );
  }

  String _formatDate(dynamic d) {
    if (d == null) return '';
    final s = d.toString();
    if (s.length >= 10) return s.substring(0, 10);
    return s;
  }

  String _contentTypeLabel(String ct) {
    if (ct.contains('image')) return 'Image';
    if (ct.contains('document')) return 'Doc';
    if (ct.contains('report')) return 'Report';
    return 'File';
  }
}

class _VaultItemTile extends StatelessWidget {
  final Map<String, dynamic> item;
  final VoidCallback onTap;
  final VoidCallback onStar;

  const _VaultItemTile({
    required this.item,
    required this.onTap,
    required this.onStar,
  });

  @override
  Widget build(BuildContext context) {
    final name = item['display_name'] ?? 'Untitled';
    final ct = (item['content_type'] ?? 'document').toString();
    final date = item['created_at'] ?? item['updated_at'] ?? '';
    final starred = item['starred'] ?? false;
    final isImage = ct.contains('image') || ct.contains('upload_image');

    return ListTile(
      leading: Icon(
        isImage ? Icons.image : Icons.description,
        color: _VaultDesign.gold,
        size: 28,
      ),
      title: Text(
        name,
        style: const TextStyle(color: _VaultDesign.textPrimary, fontSize: 14),
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
      ),
      subtitle: Row(
        children: [
          Text(
            _formatDate(date),
            style: const TextStyle(color: _VaultDesign.textSecondary, fontSize: 11),
          ),
          const SizedBox(width: 8),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
            decoration: BoxDecoration(
              color: _VaultDesign.gold.withOpacity(0.2),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text(
              _contentTypeLabel(ct),
              style: const TextStyle(color: _VaultDesign.gold, fontSize: 9),
            ),
          ),
        ],
      ),
      trailing: GestureDetector(
        onTap: onStar,
        child: Icon(
          starred ? Icons.star : Icons.star_border,
          color: starred ? _VaultDesign.gold : _VaultDesign.textSecondary,
        ),
      ),
      onTap: onTap,
    );
  }

  String _formatDate(dynamic d) {
    if (d == null) return '';
    final s = d.toString();
    if (s.length >= 10) return s.substring(0, 10);
    return s;
  }

  String _contentTypeLabel(String ct) {
    if (ct.contains('image')) return 'Image';
    if (ct.contains('document')) return 'Doc';
    if (ct.contains('report')) return 'Report';
    return 'File';
  }
}
