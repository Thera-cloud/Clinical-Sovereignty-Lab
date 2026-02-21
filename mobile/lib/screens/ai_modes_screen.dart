// =============================================================================
// AI MODES SELECTOR — Coach Portal
// Tri-Corder, Archivist, Guardian, Supervisor modes for session management
// =============================================================================

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';
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
// AI MODE DEFINITIONS
// =============================================================================
class _AIMode {
  final String id;
  final String name;
  final String description;
  final IconData icon;
  final Color color;

  const _AIMode({
    required this.id,
    required this.name,
    required this.description,
    required this.icon,
    required this.color,
  });
}

const List<_AIMode> _modes = [
  _AIMode(
    id: 'tricorder',
    name: 'Tri-Corder',
    description: 'Biometric baseline analysis and real-time monitoring',
    icon: Icons.analytics,
    color: _Design.cyan,
  ),
  _AIMode(
    id: 'archivist',
    name: 'Archivist',
    description: 'Legacy builder and historical pattern recognition',
    icon: Icons.archive,
    color: _Design.purple,
  ),
  _AIMode(
    id: 'guardian',
    name: 'Guardian',
    description: 'Parent proxy and protective oversight',
    icon: Icons.shield,
    color: _Design.green,
  ),
  _AIMode(
    id: 'supervisor',
    name: 'Supervisor',
    description: 'Session analysis and quality assurance',
    icon: Icons.visibility,
    color: _Design.gold,
  ),
];

// =============================================================================
// AI MODES SELECTOR SCREEN
// =============================================================================
class AIModesSelectorScreen extends StatefulWidget {
  final String sessionId;
  final Map<String, dynamic>? profile;

  const AIModesSelectorScreen({
    super.key,
    required this.sessionId,
    this.profile,
  });

  @override
  State<AIModesSelectorScreen> createState() => _AIModesSelectorScreenState();
}

class _AIModesSelectorScreenState extends State<AIModesSelectorScreen> {
  String _baseUrl = AppConfig.apiBaseUrl;
  String? _activeModeId;
  Map<String, dynamic>? _modeStatus;
  bool _loadingStatus = false;
  String? _statusError;

  Map<String, dynamic>? _processResult;
  Map<String, dynamic>? _outputResult;
  bool _loadingProcess = false;
  bool _loadingOutput = false;
  String? _processError;
  String? _outputError;

  @override
  void initState() {
    super.initState();
    _loadStatus();
  }

  // ===========================================================================
  // API CALLS
  // ===========================================================================
  Future<void> _loadStatus() async {
    setState(() {
      _loadingStatus = true;
      _statusError = null;
    });
    try {
      final uri = Uri.parse('$_baseUrl/api/ai-modes/status').replace(
        queryParameters: {'session_id': widget.sessionId},
      );
      final resp = await http
          .get(uri, headers: {'Content-Type': 'application/json'})
          .timeout(const Duration(seconds: 30));

      if (resp.statusCode >= 200 && resp.statusCode < 300) {
        final data = jsonDecode(resp.body);
        setState(() {
          _modeStatus = Map<String, dynamic>.from(data as Map);
          _activeModeId = _modeStatus!['active_mode']?.toString();
        });
      } else {
        throw Exception('Failed to load status: ${resp.statusCode}');
      }
    } catch (e) {
      setState(() => _statusError = e.toString());
    } finally {
      if (mounted) setState(() => _loadingStatus = false);
    }
  }

  Future<void> _activateMode(String modeId) async {
    try {
      final uri = Uri.parse('$_baseUrl/api/ai-modes/activate');
      final resp = await http
          .post(
            uri,
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'mode': modeId,
              'session_id': widget.sessionId,
            }),
          )
          .timeout(const Duration(seconds: 30));

      if (resp.statusCode >= 200 && resp.statusCode < 300) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('${_modes.firstWhere((m) => m.id == modeId).name} activated'),
            backgroundColor: _Design.green,
          ),
        );
        setState(() {
          _activeModeId = modeId;
          _processResult = null;
          _outputResult = null;
        });
        _loadStatus();
      } else {
        throw Exception('Failed to activate: ${resp.statusCode}');
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

  Future<void> _processSession() async {
    if (_activeModeId == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Please activate a mode first'),
          backgroundColor: _Design.red,
        ),
      );
      return;
    }

    setState(() {
      _loadingProcess = true;
      _processError = null;
      _processResult = null;
    });

    try {
      final uri = Uri.parse('$_baseUrl/api/ai-modes/process/${widget.sessionId}');
      final resp = await http
          .post(
            uri,
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'mode': _activeModeId}),
          )
          .timeout(const Duration(seconds: 60));

      if (resp.statusCode >= 200 && resp.statusCode < 300) {
        final data = jsonDecode(resp.body);
        setState(() {
          _processResult = Map<String, dynamic>.from(data as Map);
        });
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Processing complete'),
            backgroundColor: _Design.green,
          ),
        );
      } else {
        throw Exception('Failed to process: ${resp.statusCode}');
      }
    } catch (e) {
      setState(() => _processError = e.toString());
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Error: $e'),
            backgroundColor: _Design.red,
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _loadingProcess = false);
    }
  }

  Future<void> _getOutput() async {
    if (_activeModeId == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Please activate a mode first'),
          backgroundColor: _Design.red,
        ),
      );
      return;
    }

    setState(() {
      _loadingOutput = true;
      _outputError = null;
      _outputResult = null;
    });

    try {
      final uri = Uri.parse('$_baseUrl/api/ai-modes/output/${widget.sessionId}');
      final resp = await http
          .post(
            uri,
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'mode': _activeModeId}),
          )
          .timeout(const Duration(seconds: 60));

      if (resp.statusCode >= 200 && resp.statusCode < 300) {
        final data = jsonDecode(resp.body);
        setState(() {
          _outputResult = Map<String, dynamic>.from(data as Map);
        });
      } else {
        throw Exception('Failed to get output: ${resp.statusCode}');
      }
    } catch (e) {
      setState(() => _outputError = e.toString());
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Error: $e'),
            backgroundColor: _Design.red,
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _loadingOutput = false);
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
          'AI MODES',
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
      ),
      body: Column(
        children: [
          // Mode cards grid
          Expanded(
            flex: _activeModeId != null ? 1 : 2,
            child: _loadingStatus
                ? const Center(
                    child: CircularProgressIndicator(color: _Design.gold),
                  )
                : _statusError != null
                    ? Center(
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(Icons.error_outline,
                                color: _Design.red, size: 48),
                            const SizedBox(height: 16),
                            Text(
                              'Error loading status',
                              style: const TextStyle(color: _Design.textPrimary),
                            ),
                            const SizedBox(height: 8),
                            Text(
                              _statusError!,
                              style: const TextStyle(
                                  color: _Design.textSecondary, fontSize: 12),
                              textAlign: TextAlign.center,
                            ),
                            const SizedBox(height: 16),
                            ElevatedButton(
                              onPressed: _loadStatus,
                              style: ElevatedButton.styleFrom(
                                  backgroundColor: _Design.gold),
                              child: const Text('Retry'),
                            ),
                          ],
                        ),
                      )
                    : GridView.builder(
                        padding: const EdgeInsets.all(16),
                        gridDelegate:
                            const SliverGridDelegateWithFixedCrossAxisCount(
                          crossAxisCount: 2,
                          crossAxisSpacing: 12,
                          mainAxisSpacing: 12,
                          childAspectRatio: 0.85,
                        ),
                        itemCount: _modes.length,
                        itemBuilder: (context, index) {
                          final mode = _modes[index];
                          return _buildModeCard(mode);
                        },
                      ),
          ),
          // Active mode panel
          if (_activeModeId != null) _buildActiveModePanel(),
        ],
      ),
    );
  }

  Widget _buildModeCard(_AIMode mode) {
    final isActive = _activeModeId == mode.id;

    return Container(
      decoration: BoxDecoration(
        color: _Design.bgElevated,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: isActive ? mode.color : _Design.border,
          width: isActive ? 2 : 1,
        ),
      ),
      child: InkWell(
        onTap: () => _activateMode(mode.id),
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: mode.color.withOpacity(0.2),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Icon(mode.icon, color: mode.color, size: 32),
              ),
              const SizedBox(height: 12),
              Text(
                mode.name,
                style: TextStyle(
                  color: isActive ? mode.color : _Design.textPrimary,
                  fontSize: 16,
                  fontWeight: FontWeight.bold,
                ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 8),
              Text(
                mode.description,
                style: const TextStyle(
                  color: _Design.textSecondary,
                  fontSize: 11,
                ),
                textAlign: TextAlign.center,
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
              ),
              const Spacer(),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(vertical: 10),
                decoration: BoxDecoration(
                  color: isActive
                      ? mode.color.withOpacity(0.2)
                      : mode.color.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: mode.color),
                ),
                child: Text(
                  isActive ? 'ACTIVE' : 'ACTIVATE',
                  style: TextStyle(
                    color: mode.color,
                    fontSize: 12,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 1,
                  ),
                  textAlign: TextAlign.center,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildActiveModePanel() {
    final activeMode = _modes.firstWhere((m) => m.id == _activeModeId!);

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _Design.bgChamber,
        border: Border(
          top: BorderSide(color: _Design.border, width: 1),
        ),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(activeMode.icon, color: activeMode.color, size: 20),
              const SizedBox(width: 8),
              Text(
                '${activeMode.name} Mode Active',
                style: TextStyle(
                  color: activeMode.color,
                  fontSize: 14,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const Spacer(),
              IconButton(
                icon: const Icon(Icons.close, color: _Design.textSecondary),
                onPressed: () {
                  setState(() {
                    _activeModeId = null;
                    _processResult = null;
                    _outputResult = null;
                  });
                },
              ),
            ],
          ),
          const SizedBox(height: 16),
          // Process button
          SizedBox(
            width: double.infinity,
            child: ElevatedButton.icon(
              onPressed: _loadingProcess ? null : _processSession,
              icon: _loadingProcess
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.black,
                      ),
                    )
                  : const Icon(Icons.play_arrow, size: 18),
              label: Text(_loadingProcess ? 'Processing...' : 'Process Session'),
              style: ElevatedButton.styleFrom(
                backgroundColor: activeMode.color,
                padding: const EdgeInsets.symmetric(vertical: 14),
              ),
            ),
          ),
          // Process result
          if (_processResult != null) ...[
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: _Design.bgElevated,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: _Design.border),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Process Result:',
                    style: TextStyle(
                      color: _Design.textSecondary,
                      fontSize: 11,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    _formatResult(_processResult!),
                    style: const TextStyle(
                      color: _Design.textPrimary,
                      fontSize: 12,
                    ),
                  ),
                ],
              ),
            ),
          ],
          if (_processError != null) ...[
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: _Design.red.withOpacity(0.1),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: _Design.red),
              ),
              child: Text(
                _processError!,
                style: const TextStyle(color: _Design.red, fontSize: 11),
              ),
            ),
          ],
          // Output button
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton.icon(
              onPressed: _loadingOutput ? null : _getOutput,
              icon: _loadingOutput
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.black,
                      ),
                    )
                  : const Icon(Icons.download, size: 18),
              label: Text(_loadingOutput ? 'Loading...' : 'Get Output'),
              style: ElevatedButton.styleFrom(
                backgroundColor: _Design.purple,
                padding: const EdgeInsets.symmetric(vertical: 14),
              ),
            ),
          ),
          // Output result
          if (_outputResult != null) ...[
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: _Design.bgElevated,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: _Design.border),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Output Result:',
                    style: TextStyle(
                      color: _Design.textSecondary,
                      fontSize: 11,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    _formatResult(_outputResult!),
                    style: const TextStyle(
                      color: _Design.textPrimary,
                      fontSize: 12,
                    ),
                  ),
                ],
              ),
            ),
          ],
          if (_outputError != null) ...[
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: _Design.red.withOpacity(0.1),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: _Design.red),
              ),
              child: Text(
                _outputError!,
                style: const TextStyle(color: _Design.red, fontSize: 11),
              ),
            ),
          ],
        ],
      ),
    );
  }

  String _formatResult(Map<String, dynamic> result) {
    if (result.containsKey('message')) {
      return result['message'].toString();
    }
    if (result.containsKey('data')) {
      final data = result['data'];
      if (data is Map) {
        return data.entries
            .map((e) => '${e.key}: ${e.value}')
            .join('\n');
      }
      return data.toString();
    }
    return result.toString();
  }
}
