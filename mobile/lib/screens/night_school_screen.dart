// =============================================================================
// NIGHT SCHOOL WISDOM VIEWER — Coach Portal
// Wisdom entries, curriculum versions, training progress
// =============================================================================

import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:http/http.dart' as http;
import 'package:file_picker/file_picker.dart';
import 'dart:convert';
import 'dart:typed_data';
import '../config/app_config.dart';

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
  static const green = Color(0xFF00FF88);
  static const red = Color(0xFFEF4444);
  static const textPrimary = Color(0xFFFFFFFF);
  static const textSecondary = Color(0xFF888888);
  static const border = Color(0xFF252525);
}

// =============================================================================
// NIGHT SCHOOL SCREEN
// =============================================================================
class NightSchoolScreen extends StatefulWidget {
  final Map<String, dynamic>? profile;

  const NightSchoolScreen({super.key, this.profile});

  @override
  State<NightSchoolScreen> createState() => _NightSchoolScreenState();
}

class _NightSchoolScreenState extends State<NightSchoolScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;
  String _baseUrl = AppConfig.apiBaseUrl;

  Map<String, String> get _authHeaders => {
    'Content-Type': 'application/json',
    if ((widget.profile?['token'] ?? '').toString().isNotEmpty)
      'Authorization': 'Bearer ${widget.profile!['token']}',
  };

  // Wisdom Entries tab
  List<Map<String, dynamic>> _wisdomEntries = [];
  String _searchQuery = '';
  String? _selectedCategory;
  bool _loadingWisdom = false;
  String? _wisdomError;

  // Curriculum Status tab
  List<Map<String, dynamic>> _versions = [];
  bool _loadingVersions = false;
  String? _versionsError;

  // Training Progress tab
  Map<String, dynamic>? _stats;
  bool _loadingStats = false;
  String? _statsError;

  final TextEditingController _searchController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
    _loadAllData();
  }

  @override
  void dispose() {
    _tabController.dispose();
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _loadAllData() async {
    await Future.wait([
      _loadWisdomEntries(),
      _loadVersions(),
      _loadStats(),
    ]);
  }

  // ===========================================================================
  // WISDOM ENTRIES API
  // ===========================================================================
  Future<void> _loadWisdomEntries() async {
    setState(() {
      _loadingWisdom = true;
      _wisdomError = null;
    });
    try {
      final uri = Uri.parse('$_baseUrl/api/night-school/wisdom');
      final resp = await http
          .get(uri, headers: _authHeaders)
          .timeout(const Duration(seconds: 30));

      if (resp.statusCode >= 200 && resp.statusCode < 300) {
        final data = jsonDecode(resp.body);
        final entries = data is List
            ? data
            : (data['entries'] as List? ?? data['wisdom'] as List? ?? []);
        setState(() {
          _wisdomEntries = entries
              .map((e) => Map<String, dynamic>.from(e as Map))
              .toList();
        });
      } else {
        throw Exception('Failed to load wisdom: ${resp.statusCode}');
      }
    } catch (e) {
      setState(() => _wisdomError = e.toString());
    } finally {
      if (mounted) setState(() => _loadingWisdom = false);
    }
  }

  Future<void> _approveWisdomEntry(String entryId) async {
    try {
      final uri = Uri.parse('$_baseUrl/api/night-school/wisdom/$entryId/approve');
      final resp = await http
          .post(uri, headers: _authHeaders)
          .timeout(const Duration(seconds: 30));

      if (resp.statusCode >= 200 && resp.statusCode < 300) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Wisdom entry approved'),
            backgroundColor: _Design.green,
          ),
        );
        _loadWisdomEntries();
      } else {
        throw Exception('Failed to approve: ${resp.statusCode}');
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Error: $e'),
            backgroundColor: _Design.red,
          ),
        );
      }
    }
  }

  List<Map<String, dynamic>> get _filteredWisdomEntries {
    var filtered = _wisdomEntries;
    if (_searchQuery.isNotEmpty) {
      final query = _searchQuery.toLowerCase();
      filtered = filtered.where((e) {
        final title = (e['title'] ?? '').toString().toLowerCase();
        final content = (e['content'] ?? e['text'] ?? '').toString().toLowerCase();
        final category = (e['category'] ?? '').toString().toLowerCase();
        return title.contains(query) ||
            content.contains(query) ||
            category.contains(query);
      }).toList();
    }
    if (_selectedCategory != null) {
      filtered = filtered
          .where((e) => (e['category'] ?? '').toString() == _selectedCategory)
          .toList();
    }
    return filtered;
  }

  List<String> get _categories {
    final cats = <String>{};
    for (var e in _wisdomEntries) {
      final cat = (e['category'] ?? '').toString();
      if (cat.isNotEmpty) cats.add(cat);
    }
    return cats.toList()..sort();
  }

  // ===========================================================================
  // CURRICULUM VERSIONS API
  // ===========================================================================
  Future<void> _loadVersions() async {
    setState(() {
      _loadingVersions = true;
      _versionsError = null;
    });
    try {
      final uri = Uri.parse('$_baseUrl/api/night-school/versions');
      final resp = await http
          .get(uri, headers: _authHeaders)
          .timeout(const Duration(seconds: 30));

      if (resp.statusCode >= 200 && resp.statusCode < 300) {
        final data = jsonDecode(resp.body);
        final versions = data is List
            ? data
            : (data['versions'] as List? ?? []);
        setState(() {
          _versions = versions
              .map((v) => Map<String, dynamic>.from(v as Map))
              .toList();
        });
      } else {
        throw Exception('Failed to load versions: ${resp.statusCode}');
      }
    } catch (e) {
      setState(() => _versionsError = e.toString());
    } finally {
      if (mounted) setState(() => _loadingVersions = false);
    }
  }

  Future<void> _createSnapshot() async {
    try {
      final uri = Uri.parse('$_baseUrl/api/night-school/versions/snapshot');
      final resp = await http
          .post(uri, headers: _authHeaders)
          .timeout(const Duration(seconds: 30));

      if (resp.statusCode >= 200 && resp.statusCode < 300) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Snapshot created successfully'),
            backgroundColor: _Design.green,
          ),
        );
        _loadVersions();
      } else {
        throw Exception('Failed to create snapshot: ${resp.statusCode}');
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Error: $e'),
            backgroundColor: _Design.red,
          ),
        );
      }
    }
  }

  Future<void> _revertToVersion(String versionId) async {
    try {
      final uri = Uri.parse('$_baseUrl/api/night-school/versions/$versionId/revert');
      final resp = await http
          .post(uri, headers: _authHeaders)
          .timeout(const Duration(seconds: 30));

      if (resp.statusCode >= 200 && resp.statusCode < 300) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Reverted to version successfully'),
            backgroundColor: _Design.green,
          ),
        );
        _loadVersions();
        _loadWisdomEntries();
      } else {
        throw Exception('Failed to revert: ${resp.statusCode}');
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Error: $e'),
            backgroundColor: _Design.red,
          ),
        );
      }
    }
  }

  Future<void> _uploadCurriculum() async {
    try {
      final result = await FilePicker.platform.pickFiles(
        allowMultiple: false,
        type: FileType.custom,
        allowedExtensions: ['json', 'txt', 'md', 'csv'],
      );
      if (result == null || result.files.isEmpty) return;
      final file = result.files.single;
      Uint8List? bytes = file.bytes;
      if (bytes == null && file.path != null && !kIsWeb) {
        return;
      }
      if (bytes == null) return;

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Uploading curriculum...'), backgroundColor: _Design.cyan),
        );
      }

      final uri = Uri.parse('${AppConfig.apiBaseUrl}/api/night-school/curriculum/upload');
      final request = http.MultipartRequest('POST', uri);
      final token = (widget.profile?['token'] ?? '').toString();
      if (token.isNotEmpty) request.headers['Authorization'] = 'Bearer $token';
      request.fields['category'] = 'general';
      request.files.add(http.MultipartFile.fromBytes('file', bytes, filename: file.name));
      final streamed = await request.send().timeout(const Duration(seconds: 60));
      final resp = await http.Response.fromStream(streamed);

      if (!mounted) return;
      if (resp.statusCode >= 200 && resp.statusCode < 300) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Curriculum uploaded successfully'), backgroundColor: _Design.green),
        );
        _loadVersions();
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Upload failed: ${resp.statusCode}'), backgroundColor: _Design.red),
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

  // ===========================================================================
  // TRAINING STATS API
  // ===========================================================================
  Future<void> _loadStats() async {
    setState(() {
      _loadingStats = true;
      _statsError = null;
    });
    try {
      final uri = Uri.parse('$_baseUrl/api/night-school/stats');
      final resp = await http
          .get(uri, headers: _authHeaders)
          .timeout(const Duration(seconds: 30));

      if (resp.statusCode >= 200 && resp.statusCode < 300) {
        final data = jsonDecode(resp.body);
        setState(() {
          _stats = Map<String, dynamic>.from(data as Map);
        });
      } else {
        throw Exception('Failed to load stats: ${resp.statusCode}');
      }
    } catch (e) {
      setState(() => _statsError = e.toString());
    } finally {
      if (mounted) setState(() => _loadingStats = false);
    }
  }

  // ===========================================================================
  // UI BUILDERS
  // ===========================================================================
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _Design.bgVoid,
      appBar: AppBar(
        backgroundColor: _Design.bgChamber,
        title: const Text(
          'NIGHT SCHOOL',
          style: TextStyle(
            color: _Design.gold,
            fontSize: 16,
            letterSpacing: 3,
            fontFamily: 'Courier',
            fontWeight: FontWeight.bold,
          ),
        ),
        centerTitle: true,
        iconTheme: const IconThemeData(color: _Design.textPrimary),
        bottom: TabBar(
          controller: _tabController,
          indicatorColor: _Design.gold,
          labelColor: _Design.gold,
          unselectedLabelColor: _Design.textSecondary,
          tabs: const [
            Tab(text: 'Wisdom Entries'),
            Tab(text: 'Curriculum Status'),
            Tab(text: 'Training Progress'),
          ],
        ),
      ),
      body: TabBarView(
        controller: _tabController,
        children: [
          _buildWisdomTab(),
          _buildCurriculumTab(),
          _buildTrainingTab(),
        ],
      ),
    );
  }

  Widget _buildWisdomTab() {
    if (_loadingWisdom) {
      return const Center(
        child: CircularProgressIndicator(color: _Design.gold),
      );
    }

    if (_wisdomError != null) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.error_outline, color: _Design.red, size: 48),
            const SizedBox(height: 16),
            Text(
              'Error loading wisdom',
              style: const TextStyle(color: _Design.textPrimary),
            ),
            const SizedBox(height: 8),
            Text(
              _wisdomError!,
              style: const TextStyle(color: _Design.textSecondary, fontSize: 12),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: _loadWisdomEntries,
              style: ElevatedButton.styleFrom(backgroundColor: _Design.gold),
              child: const Text('Retry'),
            ),
          ],
        ),
      );
    }

    return Column(
      children: [
        // Search and filter bar
        Container(
          padding: const EdgeInsets.all(16),
          color: _Design.bgChamber,
          child: Column(
            children: [
              TextField(
                controller: _searchController,
                style: const TextStyle(color: _Design.textPrimary),
                decoration: InputDecoration(
                  hintText: 'Search wisdom entries...',
                  hintStyle: const TextStyle(color: _Design.textSecondary),
                  prefixIcon: const Icon(Icons.search, color: _Design.gold),
                  suffixIcon: _searchQuery.isNotEmpty
                      ? IconButton(
                          icon: const Icon(Icons.clear, color: _Design.textSecondary),
                          onPressed: () {
                            _searchController.clear();
                            setState(() => _searchQuery = '');
                          },
                        )
                      : null,
                  filled: true,
                  fillColor: _Design.bgElevated,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(8),
                    borderSide: const BorderSide(color: _Design.border),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(8),
                    borderSide: const BorderSide(color: _Design.border),
                  ),
                  focusedBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(8),
                    borderSide: const BorderSide(color: _Design.gold),
                  ),
                ),
                onChanged: (value) {
                  setState(() => _searchQuery = value);
                },
              ),
              if (_categories.isNotEmpty) ...[
                const SizedBox(height: 12),
                SizedBox(
                  height: 36,
                  child: ListView(
                    scrollDirection: Axis.horizontal,
                    children: [
                      _buildCategoryChip(null),
                      const SizedBox(width: 8),
                      ..._categories.map((cat) => Padding(
                            padding: const EdgeInsets.only(right: 8),
                            child: _buildCategoryChip(cat),
                          )),
                    ],
                  ),
                ),
              ],
            ],
          ),
        ),
        // Wisdom entries list
        Expanded(
          child: _filteredWisdomEntries.isEmpty
              ? Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.book_outlined,
                          color: _Design.textSecondary, size: 48),
                      const SizedBox(height: 16),
                      Text(
                        _wisdomEntries.isEmpty
                            ? 'No wisdom entries found'
                            : 'No entries match your search',
                        style: const TextStyle(color: _Design.textSecondary),
                      ),
                    ],
                  ),
                )
              : ListView.builder(
                  padding: const EdgeInsets.all(16),
                  itemCount: _filteredWisdomEntries.length,
                  itemBuilder: (context, index) {
                    final entry = _filteredWisdomEntries[index];
                    return _buildWisdomEntryCard(entry);
                  },
                ),
        ),
      ],
    );
  }

  Widget _buildCategoryChip(String? category) {
    final isSelected = _selectedCategory == category;
    return FilterChip(
      label: Text(category ?? 'All'),
      selected: isSelected,
      onSelected: (selected) {
        setState(() => _selectedCategory = selected ? category : null);
      },
      selectedColor: _Design.gold.withOpacity(0.3),
      checkmarkColor: _Design.gold,
      labelStyle: TextStyle(
        color: isSelected ? _Design.gold : _Design.textPrimary,
        fontSize: 12,
      ),
      side: BorderSide(
        color: isSelected ? _Design.gold : _Design.border,
      ),
    );
  }

  Widget _buildWisdomEntryCard(Map<String, dynamic> entry) {
    final category = (entry['category'] ?? '').toString();
    final title = (entry['title'] ?? 'Untitled').toString();
    final content = (entry['content'] ?? entry['text'] ?? '').toString();
    final approved = entry['approved'] == true;
    final entryId = (entry['id'] ?? entry['_id'] ?? '').toString();

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _Design.bgElevated,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _Design.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              if (category.isNotEmpty)
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: _Design.purple.withOpacity(0.2),
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(color: _Design.purple),
                  ),
                  child: Text(
                    category,
                    style: const TextStyle(
                      color: _Design.purple,
                      fontSize: 11,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              const Spacer(),
              if (approved)
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: _Design.green.withOpacity(0.2),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: const Text(
                    'APPROVED',
                    style: TextStyle(
                      color: _Design.green,
                      fontSize: 10,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            title,
            style: const TextStyle(
              color: _Design.textPrimary,
              fontSize: 16,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            content.length > 200 ? '${content.substring(0, 200)}...' : content,
            style: const TextStyle(
              color: _Design.textSecondary,
              fontSize: 13,
            ),
          ),
          if (!approved) ...[
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: () => _approveWisdomEntry(entryId),
                style: ElevatedButton.styleFrom(
                  backgroundColor: _Design.green,
                  padding: const EdgeInsets.symmetric(vertical: 12),
                ),
                child: const Text(
                  'Approve Entry',
                  style: TextStyle(
                    color: Colors.black,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildCurriculumTab() {
    if (_loadingVersions) {
      return const Center(
        child: CircularProgressIndicator(color: _Design.gold),
      );
    }

    if (_versionsError != null) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.error_outline, color: _Design.red, size: 48),
            const SizedBox(height: 16),
            Text(
              'Error loading versions',
              style: const TextStyle(color: _Design.textPrimary),
            ),
            const SizedBox(height: 8),
            Text(
              _versionsError!,
              style: const TextStyle(color: _Design.textSecondary, fontSize: 12),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: _loadVersions,
              style: ElevatedButton.styleFrom(backgroundColor: _Design.gold),
              child: const Text('Retry'),
            ),
          ],
        ),
      );
    }

    return Column(
      children: [
        // Action buttons
        Container(
          padding: const EdgeInsets.all(16),
          color: _Design.bgChamber,
          child: Row(
            children: [
              Expanded(
                child: ElevatedButton.icon(
                  onPressed: _createSnapshot,
                  icon: const Icon(Icons.camera_alt, size: 18),
                  label: const Text('Create Snapshot'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: _Design.cyan,
                    padding: const EdgeInsets.symmetric(vertical: 12),
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: ElevatedButton.icon(
                  onPressed: _uploadCurriculum,
                  icon: const Icon(Icons.upload, size: 18),
                  label: const Text('Upload'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: _Design.purple,
                    padding: const EdgeInsets.symmetric(vertical: 12),
                  ),
                ),
              ),
            ],
          ),
        ),
        // Versions list
        Expanded(
          child: _versions.isEmpty
              ? Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.history,
                          color: _Design.textSecondary, size: 48),
                      const SizedBox(height: 16),
                      const Text(
                        'No curriculum versions found',
                        style: TextStyle(color: _Design.textSecondary),
                      ),
                    ],
                  ),
                )
              : ListView.builder(
                  padding: const EdgeInsets.all(16),
                  itemCount: _versions.length,
                  itemBuilder: (context, index) {
                    final version = _versions[index];
                    return _buildVersionCard(version);
                  },
                ),
        ),
      ],
    );
  }

  Widget _buildVersionCard(Map<String, dynamic> version) {
    final versionId = (version['id'] ?? version['_id'] ?? '').toString();
    final versionName = (version['name'] ?? version['version'] ?? 'Unknown')
        .toString();
    final createdAt = (version['created_at'] ?? version['timestamp'] ?? '')
        .toString();
    final isCurrent = version['is_current'] == true;

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _Design.bgElevated,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: isCurrent ? _Design.gold : _Design.border,
          width: isCurrent ? 2 : 1,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  versionName,
                  style: TextStyle(
                    color: isCurrent ? _Design.gold : _Design.textPrimary,
                    fontSize: 16,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
              if (isCurrent)
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: _Design.gold.withOpacity(0.2),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: const Text(
                    'CURRENT',
                    style: TextStyle(
                      color: _Design.gold,
                      fontSize: 10,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
            ],
          ),
          if (createdAt.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              'Created: $createdAt',
              style: const TextStyle(
                color: _Design.textSecondary,
                fontSize: 12,
              ),
            ),
          ],
          if (!isCurrent) ...[
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton(
                onPressed: () => _revertToVersion(versionId),
                style: OutlinedButton.styleFrom(
                  side: const BorderSide(color: _Design.gold),
                  padding: const EdgeInsets.symmetric(vertical: 12),
                ),
                child: const Text(
                  'Revert to This Version',
                  style: TextStyle(color: _Design.gold),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildTrainingTab() {
    if (_loadingStats) {
      return const Center(
        child: CircularProgressIndicator(color: _Design.gold),
      );
    }

    if (_statsError != null) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.error_outline, color: _Design.red, size: 48),
            const SizedBox(height: 16),
            Text(
              'Error loading stats',
              style: const TextStyle(color: _Design.textPrimary),
            ),
            const SizedBox(height: 8),
            Text(
              _statsError!,
              style: const TextStyle(color: _Design.textSecondary, fontSize: 12),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: _loadStats,
              style: ElevatedButton.styleFrom(backgroundColor: _Design.gold),
              child: const Text('Retry'),
            ),
          ],
        ),
      );
    }

    if (_stats == null) {
      return const Center(
        child: Text(
          'No stats available',
          style: TextStyle(color: _Design.textSecondary),
        ),
      );
    }

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _buildStatCard(
          'Total Wisdom Entries',
          _stats!['total_wisdom_entries']?.toString() ?? '0',
          Icons.book,
          _Design.purple,
        ),
        const SizedBox(height: 12),
        _buildStatCard(
          'Total Versions',
          _stats!['total_versions']?.toString() ?? '0',
          Icons.history,
          _Design.cyan,
        ),
        const SizedBox(height: 12),
        _buildStatCard(
          'Approved Entries',
          _stats!['approved_entries']?.toString() ?? '0',
          Icons.check_circle,
          _Design.green,
        ),
        const SizedBox(height: 12),
        _buildStatCard(
          'Pending Entries',
          _stats!['pending_entries']?.toString() ?? '0',
          Icons.pending,
          _Design.gold,
        ),
        if (_stats!['last_training_date'] != null) ...[
          const SizedBox(height: 12),
          _buildStatCard(
            'Last Training',
            _stats!['last_training_date'].toString(),
            Icons.schedule,
            _Design.cyan,
          ),
        ],
      ],
    );
  }

  Widget _buildStatCard(String label, String value, IconData icon, Color color) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: _Design.bgElevated,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _Design.border),
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: color.withOpacity(0.2),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(icon, color: color, size: 24),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: const TextStyle(
                    color: _Design.textSecondary,
                    fontSize: 12,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  value,
                  style: TextStyle(
                    color: color,
                    fontSize: 24,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
