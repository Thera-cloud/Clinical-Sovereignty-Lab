// =============================================================================
// COACHING MESH SCREEN — Master/Assistant BLE Group Training Sessions
// Quiz dispatch, scenario practice, discussion, Little Nate AI integration,
// DOJO method-specific layouts (timed/progressive/adversarial/presentation)
// =============================================================================

import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:http/http.dart' as http;

import '../config/app_config.dart';

// Conditional BLE import
import 'community_mesh_ble.dart' if (dart.library.html) 'community_mesh_ble_stub.dart'
    as ble;

// =============================================================================
// DESIGN TOKENS
// =============================================================================
class _D {
  static const bgVoid = Color(0xFF050505);
  static const bgChamber = Color(0xFF0A0A0A);
  static const bgElevated = Color(0xFF111111);
  static const bgCard = Color(0xFF1A1A1A);
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
enum CoachingMeshState { IDLE, DISCOVERING, FORMING, ACTIVE, CLOSING }

// =============================================================================
// PARTICIPANT MODEL
// =============================================================================
class MeshParticipant {
  final String userId;
  final String username;
  final String role;
  bool connected;
  MeshParticipant({
    required this.userId,
    required this.username,
    required this.role,
    this.connected = true,
  });
}

// =============================================================================
// CHAT MESSAGE MODEL
// =============================================================================
class MeshChatMessage {
  final String senderId;
  final String senderName;
  final String content;
  final String type;
  final double? score;
  final DateTime timestamp;
  final bool isNate;

  MeshChatMessage({
    required this.senderId,
    required this.senderName,
    required this.content,
    this.type = 'discussion',
    this.score,
    DateTime? timestamp,
  })  : isNate = senderId == 'nate',
        timestamp = timestamp ?? DateTime.now();
}

// =============================================================================
// QUIZ QUESTION MODEL
// =============================================================================
class MeshQuizQuestion {
  final int index;
  final String text;
  final String type;
  final List<String>? options;
  String? selectedAnswer;
  bool submitted;
  double? score;
  String? feedback;

  MeshQuizQuestion({
    required this.index,
    required this.text,
    this.type = 'open_text',
    this.options,
    this.selectedAnswer,
    this.submitted = false,
    this.score,
    this.feedback,
  });
}

// =============================================================================
// MAIN SCREEN
// =============================================================================
class CoachingMeshScreen extends StatefulWidget {
  final Map<String, dynamic> profile;
  final String token;
  final bool isMaster;

  const CoachingMeshScreen({
    super.key,
    required this.profile,
    required this.token,
    this.isMaster = false,
  });

  @override
  State<CoachingMeshScreen> createState() => _CoachingMeshScreenState();
}

class _CoachingMeshScreenState extends State<CoachingMeshScreen>
    with TickerProviderStateMixin {
  CoachingMeshState _state = CoachingMeshState.IDLE;
  String? _sessionId;
  String _sessionTitle = '';
  String _sessionType = 'group_discussion';
  String? _dojoContext;
  bool _nateParticipation = true;

  final List<MeshParticipant> _participants = [];
  final List<MeshChatMessage> _messages = [];
  final List<MeshQuizQuestion> _quizQuestions = [];
  String? _scenarioDescription;
  String? _scenarioDojoType;

  final TextEditingController _chatController = TextEditingController();
  final TextEditingController _titleController = TextEditingController();
  final ScrollController _scrollController = ScrollController();

  late TabController _tabController;
  WebSocketChannel? _wsChannel;
  StreamSubscription? _wsSubscription;
  bool _isLoading = false;
  String? _errorMessage;

  // Timer for timed methods
  Timer? _countdownTimer;
  int _remainingSeconds = 0;
  bool _isTimed = false;

  // BLE discovery
  Timer? _discoveryTimer;
  bool _discoveryTimedOut = false;

  // Available DOJO types and methods
  final List<String> _dojoTypes = [
    'therapist', 'judge', 'business', 'mcat', 'cnc', 'teacher', 'project_pm', 'coach_nate',
  ];
  final Map<String, String> _dojoLabels = {
    'therapist': 'Therapist', 'judge': 'Judge', 'business': 'Business',
    'mcat': 'MCAT', 'cnc': 'CNC', 'teacher': 'Teacher', 'project_pm': 'Project PM',
    'coach_nate': 'Coach Nate',
  };

  final List<Map<String, String>> _generalTypes = [
    {'id': 'group_discussion', 'name': 'Group Discussion'},
    {'id': 'quiz_drill', 'name': 'Quiz Drill'},
    {'id': 'scenario_practice', 'name': 'Scenario Practice'},
    {'id': 'case_review', 'name': 'Case Review'},
  ];
  List<Map<String, dynamic>> _dojoMethods = [];
  bool _wsAuthed = false;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
    _connectWebSocket();
  }

  @override
  void dispose() {
    _wsSubscription?.cancel();
    _wsChannel?.sink.close();
    _chatController.dispose();
    _titleController.dispose();
    _scrollController.dispose();
    _tabController.dispose();
    _countdownTimer?.cancel();
    _discoveryTimer?.cancel();
    super.dispose();
  }

  void _startBleDiscovery() {
    setState(() {
      _state = CoachingMeshState.DISCOVERING;
      _discoveryTimedOut = false;
    });
    _discoveryTimer?.cancel();
    _discoveryTimer = Timer(const Duration(seconds: 10), () {
      if (mounted && _state == CoachingMeshState.DISCOVERING) {
        setState(() => _discoveryTimedOut = true);
      }
    });
  }

  // ── WebSocket ──

  void _connectWebSocket() {
    final wsUrl = AppConfig.wsUrl;
    _wsChannel = WebSocketChannel.connect(Uri.parse(wsUrl));
    _wsSubscription = _wsChannel!.stream.listen(
      _onWsMessage,
      onError: (e) => setState(() => _errorMessage = 'Connection error'),
      onDone: () {
        if (_state == CoachingMeshState.ACTIVE) {
          setState(() => _state = CoachingMeshState.CLOSING);
        }
      },
    );
    _wsAuthed = false;
    _wsChannel!.sink.add(jsonEncode({
      'type': 'auth',
      'token': widget.token,
      'hardware_id': widget.profile['hardware_id'],
      'client_context': 'coaching_mesh',
    }));
  }

  void _onWsMessage(dynamic raw) {
    final msg = jsonDecode(raw as String) as Map<String, dynamic>;
    final type = msg['type'] as String? ?? '';

    switch (type) {
      case 'auth_success':
        setState(() {
          _wsAuthed = true;
          _errorMessage = null;
        });
        break;
      case 'auth_failed':
        setState(() {
          _wsAuthed = false;
          _isLoading = false;
          _errorMessage = msg['message']?.toString() ?? 'Auth failed';
        });
        break;
      case 'coaching_mesh_created':
        setState(() {
          _sessionId = msg['session_id'];
          _state = CoachingMeshState.ACTIVE;
          _isLoading = false;
          _participants.add(MeshParticipant(
            userId: widget.profile['hardware_id'] ?? '',
            username: widget.profile['username'] ?? 'Master',
            role: 'master',
          ));
        });
        break;

      case 'coaching_mesh_joined':
        setState(() {
          _sessionId = msg['session_id'];
          _state = CoachingMeshState.ACTIVE;
          _isLoading = false;
        });
        break;

      case 'coaching_mesh_participant_joined':
        setState(() {
          _participants.add(MeshParticipant(
            userId: msg['user_id'] ?? '',
            username: msg['username'] ?? 'Participant',
            role: msg['role'] ?? 'assistant',
          ));
          _messages.add(MeshChatMessage(
            senderId: 'system',
            senderName: 'System',
            content: '${msg['username']} joined the session',
            type: 'system',
          ));
        });
        break;

      case 'coaching_mesh_message_received':
        setState(() {
          _messages.add(MeshChatMessage(
            senderId: msg['sender_id'] ?? '',
            senderName: msg['sender_username'] ?? 'Unknown',
            content: msg['content'] ?? '',
          ));
        });
        _scrollToBottom();
        break;

      case 'coaching_mesh_quiz_received':
        final questions = msg['questions'] as List? ?? [];
        setState(() {
          _quizQuestions.clear();
          for (var i = 0; i < questions.length; i++) {
            final q = questions[i];
            _quizQuestions.add(MeshQuizQuestion(
              index: i,
              text: q['text'] ?? '',
              type: q['type'] ?? 'open_text',
              options: (q['options'] as List?)?.map((e) => e.toString()).toList(),
            ));
          }
          _tabController.animateTo(1);
        });
        break;

      case 'coaching_mesh_answer_scored':
        setState(() {
          final idx = msg['question_index'] as int? ?? 0;
          if (idx < _quizQuestions.length) {
            _quizQuestions[idx].score = (msg['score'] as num?)?.toDouble();
            _quizQuestions[idx].feedback = msg['feedback']?.toString();
            _quizQuestions[idx].submitted = true;
          }
        });
        break;

      case 'coaching_mesh_answer_received':
        setState(() {
          _messages.add(MeshChatMessage(
            senderId: msg['user_id'] ?? '',
            senderName: msg['username'] ?? '',
            content: 'Answered Q${(msg['question_index'] ?? 0) + 1} — Score: ${msg['score'] ?? '...'}',
            type: 'quiz_answer',
            score: (msg['score'] as num?)?.toDouble(),
          ));
        });
        break;

      case 'coaching_mesh_scenario_received':
        setState(() {
          _scenarioDescription = msg['description'];
          _scenarioDojoType = msg['dojo_type'];
          _tabController.animateTo(2);
        });
        break;

      case 'coaching_mesh_nate_response':
        setState(() {
          _messages.add(MeshChatMessage(
            senderId: 'nate',
            senderName: 'Little Nate',
            content: msg['feedback'] ?? '',
            type: 'nate_feedback',
          ));
        });
        _scrollToBottom();
        break;

      case 'coaching_mesh_scores_data':
        _showScoresDialog(msg['scores'] as Map<String, dynamic>? ?? {});
        break;

      case 'coaching_mesh_ended':
        setState(() {
          _state = CoachingMeshState.CLOSING;
          _messages.add(MeshChatMessage(
            senderId: 'system',
            senderName: 'System',
            content: 'Session ended by master coach',
            type: 'system',
          ));
        });
        break;

      case 'coaching_mesh_error':
        setState(() {
          _errorMessage = msg['message']?.toString();
          _isLoading = false;
        });
        break;
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  // ── Actions ──

  void _createSession() {
    if (_titleController.text.isEmpty) {
      setState(() => _errorMessage = 'Please enter a session title');
      return;
    }
    if (!_wsAuthed) {
      setState(() => _errorMessage = 'Still connecting — try again in a moment');
      return;
    }
    setState(() => _isLoading = true);
    _wsChannel?.sink.add(jsonEncode({
      'type': 'coaching_mesh_create',
      'title': _titleController.text,
      'session_type': _sessionType,
      'dojo_context': _dojoContext,
      'nate_participation': _nateParticipation,
    }));
  }

  void _joinSession(String sessionId) {
    if (!_wsAuthed) {
      setState(() => _errorMessage = 'Still connecting — try again in a moment');
      return;
    }
    setState(() => _isLoading = true);
    _wsChannel?.sink.add(jsonEncode({
      'type': 'coaching_mesh_join',
      'session_id': sessionId,
    }));
  }

  void _sendMessage() {
    final text = _chatController.text.trim();
    if (text.isEmpty || _sessionId == null) return;

    if (text.startsWith('@nate')) {
      _wsChannel?.sink.add(jsonEncode({
        'type': 'coaching_mesh_ask_nate',
        'session_id': _sessionId,
        'context': _messages.reversed.take(10).map((m) => '${m.senderName}: ${m.content}').join('\n'),
        'prompt': text.replaceFirst('@nate', '').trim(),
      }));
    } else {
      _wsChannel?.sink.add(jsonEncode({
        'type': 'coaching_mesh_message',
        'session_id': _sessionId,
        'content': text,
      }));
    }
    _chatController.clear();
  }

  void _submitQuizAnswer(int index, String answer) {
    _wsChannel?.sink.add(jsonEncode({
      'type': 'coaching_mesh_answer',
      'session_id': _sessionId,
      'question_index': index,
      'answer': answer,
    }));
  }

  void _pushQuiz(List<Map<String, dynamic>> questions) {
    _wsChannel?.sink.add(jsonEncode({
      'type': 'coaching_mesh_push_quiz',
      'session_id': _sessionId,
      'questions': questions,
    }));
  }

  void _pushScenario(String dojoType, String persona, String description) {
    _wsChannel?.sink.add(jsonEncode({
      'type': 'coaching_mesh_push_scenario',
      'session_id': _sessionId,
      'dojo_type': dojoType,
      'persona': persona,
      'description': description,
    }));
  }

  void _requestScores() {
    _wsChannel?.sink.add(jsonEncode({
      'type': 'coaching_mesh_scores',
      'session_id': _sessionId,
    }));
  }

  void _endSession() {
    _wsChannel?.sink.add(jsonEncode({
      'type': 'coaching_mesh_end',
      'session_id': _sessionId,
    }));
  }

  void _leaveSession() {
    _wsChannel?.sink.add(jsonEncode({
      'type': 'coaching_mesh_leave',
      'session_id': _sessionId,
    }));
    setState(() => _state = CoachingMeshState.IDLE);
  }

  void _loadDojoMethods(String dojoType) async {
    try {
      final url = '${AppConfig.apiBaseUrl}/api/coach/mesh/methods/$dojoType';
      final resp = await http.get(
        Uri.parse(url),
        headers: {'Authorization': 'Bearer ${widget.token}'},
      );
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        setState(() {
          _dojoMethods = (data['methods'] as List?)
                  ?.map<Map<String, dynamic>>((m) => Map<String, dynamic>.from(m))
                  .toList() ??
              [];
        });
      }
    } catch (e) {
      debugPrint('Failed to load DOJO methods: $e');
    }
  }

  // ── Dialogs ──

  void _showScoresDialog(Map<String, dynamic> scores) {
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: _D.bgElevated,
        title: const Text('Session Scores', style: TextStyle(color: _D.gold)),
        content: SizedBox(
          width: 300,
          child: ListView(
            shrinkWrap: true,
            children: scores.entries.map((e) {
              final data = e.value as Map<String, dynamic>? ?? {};
              return ListTile(
                title: Text(e.key, style: const TextStyle(color: _D.textPrimary)),
                trailing: Text(
                  '${((data['average'] as num?)?.toStringAsFixed(2) ?? '—')}',
                  style: const TextStyle(color: _D.gold, fontSize: 16, fontWeight: FontWeight.bold),
                ),
                subtitle: Text(
                  '${data['count'] ?? 0} responses',
                  style: const TextStyle(color: _D.textSecondary, fontSize: 12),
                ),
              );
            }).toList(),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Close', style: TextStyle(color: _D.gold)),
          ),
        ],
      ),
    );
  }

  void _showPushQuizDialog() {
    final questionControllers = [TextEditingController()];
    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          backgroundColor: _D.bgElevated,
          title: const Text('Push Quiz', style: TextStyle(color: _D.gold)),
          content: SizedBox(
            width: 350,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                ...questionControllers.asMap().entries.map((e) => Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: TextField(
                        controller: e.value,
                        style: const TextStyle(color: _D.textPrimary),
                        decoration: InputDecoration(
                          labelText: 'Question ${e.key + 1}',
                          labelStyle: const TextStyle(color: _D.textSecondary),
                          enabledBorder: const UnderlineInputBorder(
                            borderSide: BorderSide(color: _D.goldDim),
                          ),
                        ),
                      ),
                    )),
                TextButton.icon(
                  onPressed: () {
                    setDialogState(() => questionControllers.add(TextEditingController()));
                  },
                  icon: const Icon(Icons.add, color: _D.cyan, size: 16),
                  label: const Text('Add Question', style: TextStyle(color: _D.cyan)),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cancel', style: TextStyle(color: _D.textSecondary)),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: _D.gold),
              onPressed: () {
                final questions = questionControllers
                    .where((c) => c.text.isNotEmpty)
                    .map((c) => {'text': c.text, 'type': 'open_text'})
                    .toList();
                if (questions.isNotEmpty) {
                  _pushQuiz(questions.cast<Map<String, dynamic>>());
                }
                Navigator.pop(ctx);
              },
              child: const Text('Push', style: TextStyle(color: Colors.black)),
            ),
          ],
        ),
      ),
    );
  }

  void _showPushScenarioDialog() {
    String selectedDojo = _dojoContext ?? 'therapist';
    final descController = TextEditingController();
    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          backgroundColor: _D.bgElevated,
          title: const Text('Push Scenario', style: TextStyle(color: _D.gold)),
          content: SizedBox(
            width: 350,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                DropdownButtonFormField<String>(
                  value: selectedDojo,
                  dropdownColor: _D.bgElevated,
                  style: const TextStyle(color: _D.textPrimary),
                  decoration: const InputDecoration(
                    labelText: 'DOJO',
                    labelStyle: TextStyle(color: _D.textSecondary),
                  ),
                  items: _dojoTypes.map((d) => DropdownMenuItem(
                    value: d,
                    child: Text(_dojoLabels[d] ?? d),
                  )).toList(),
                  onChanged: (v) => setDialogState(() => selectedDojo = v ?? selectedDojo),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: descController,
                  style: const TextStyle(color: _D.textPrimary),
                  maxLines: 4,
                  decoration: const InputDecoration(
                    labelText: 'Scenario Description',
                    labelStyle: TextStyle(color: _D.textSecondary),
                    enabledBorder: OutlineInputBorder(
                      borderSide: BorderSide(color: _D.goldDim),
                    ),
                  ),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cancel', style: TextStyle(color: _D.textSecondary)),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: _D.gold),
              onPressed: () {
                if (descController.text.isNotEmpty) {
                  _pushScenario(selectedDojo, selectedDojo, descController.text);
                }
                Navigator.pop(ctx);
              },
              child: const Text('Push', style: TextStyle(color: Colors.black)),
            ),
          ],
        ),
      ),
    );
  }

  // ── BUILD ──

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _D.bgVoid,
      appBar: AppBar(
        backgroundColor: _D.bgChamber,
        iconTheme: const IconThemeData(color: _D.gold),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => Navigator.of(context).pop(),
        ),
        title: Text(
          _state == CoachingMeshState.ACTIVE
              ? _sessionTitle.isNotEmpty ? _sessionTitle : 'Training Session'
              : 'Coaching Mesh',
          style: const TextStyle(color: _D.gold, fontFamily: 'Cormorant Garamond'),
        ),
        actions: [
          if (_state == CoachingMeshState.ACTIVE) ...[
            IconButton(
              icon: const Icon(Icons.people, color: _D.cyan),
              tooltip: 'Participants (${_participants.length})',
              onPressed: () => _showParticipantsSheet(),
            ),
            if (widget.isMaster) ...[
              IconButton(
                icon: const Icon(Icons.scoreboard, color: _D.gold),
                tooltip: 'Scores',
                onPressed: _requestScores,
              ),
              IconButton(
                icon: const Icon(Icons.stop_circle, color: _D.red),
                tooltip: 'End Session',
                onPressed: _endSession,
              ),
            ] else
              IconButton(
                icon: const Icon(Icons.exit_to_app, color: _D.red),
                tooltip: 'Leave',
                onPressed: _leaveSession,
              ),
          ],
        ],
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_errorMessage != null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline, color: _D.red, size: 48),
            const SizedBox(height: 12),
            Text(_errorMessage!, style: const TextStyle(color: _D.red)),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: () => setState(() => _errorMessage = null),
              child: const Text('Dismiss'),
            ),
          ],
        ),
      );
    }

    switch (_state) {
      case CoachingMeshState.IDLE:
        return widget.isMaster ? _buildCreateView() : _buildJoinView();
      case CoachingMeshState.DISCOVERING:
        return _buildDiscoveringView();
      case CoachingMeshState.FORMING:
      case CoachingMeshState.ACTIVE:
        return _buildActiveView();
      case CoachingMeshState.CLOSING:
        return _buildClosingView();
    }
  }

  Widget _buildCreateView() {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('CREATE TRAINING SESSION',
              style: TextStyle(color: _D.gold, fontSize: 18, fontWeight: FontWeight.bold,
                  fontFamily: 'Cormorant Garamond', letterSpacing: 2)),
          const SizedBox(height: 24),

          TextField(
            controller: _titleController,
            style: const TextStyle(color: _D.textPrimary),
            decoration: const InputDecoration(
              labelText: 'Session Title',
              labelStyle: TextStyle(color: _D.textSecondary),
              enabledBorder: UnderlineInputBorder(borderSide: BorderSide(color: _D.goldDim)),
              focusedBorder: UnderlineInputBorder(borderSide: BorderSide(color: _D.gold)),
            ),
          ),
          const SizedBox(height: 20),

          const Text('DOJO Context (optional)', style: TextStyle(color: _D.textSecondary, fontSize: 12)),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _dojoChip(null, 'None'),
              ..._dojoTypes.map((d) => _dojoChip(d, _dojoLabels[d] ?? d)),
            ],
          ),
          const SizedBox(height: 20),

          const Text('SESSION TYPE', style: TextStyle(color: _D.textSecondary, fontSize: 12)),
          const SizedBox(height: 8),
          ..._generalTypes.map((t) => _typeRadio(t['id']!, t['name']!)),
          if (_dojoMethods.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text('${_dojoLabels[_dojoContext] ?? ''} METHODS',
                style: const TextStyle(color: _D.cyan, fontSize: 12)),
            ..._dojoMethods.map((m) => _typeRadio(
              m['id'] as String,
              '${m['name']}${m['time_pressure'] == true ? ' ⏱' : ''}',
              subtitle: m['description'] as String?,
            )),
          ],
          const SizedBox(height: 20),

          SwitchListTile(
            title: const Text('Little Nate Participation', style: TextStyle(color: _D.textPrimary)),
            subtitle: const Text('AI assists, evaluates, and provides feedback',
                style: TextStyle(color: _D.textSecondary, fontSize: 12)),
            value: _nateParticipation,
            activeColor: _D.cyan,
            onChanged: (v) => setState(() => _nateParticipation = v),
          ),
          const SizedBox(height: 30),

          SizedBox(
            width: double.infinity,
            child: ElevatedButton.icon(
              style: ElevatedButton.styleFrom(
                backgroundColor: _D.gold,
                padding: const EdgeInsets.symmetric(vertical: 16),
              ),
              onPressed: _isLoading ? null : _createSession,
              icon: _isLoading
                  ? const SizedBox(width: 20, height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black))
                  : const Icon(Icons.play_arrow, color: Colors.black),
              label: Text(_isLoading ? 'Creating...' : 'Start Training Session',
                  style: const TextStyle(color: Colors.black, fontWeight: FontWeight.bold)),
            ),
          ),
        ],
      ),
    );
  }

  Widget _dojoChip(String? value, String label) {
    final selected = _dojoContext == value;
    return ChoiceChip(
      label: Text(label, style: TextStyle(
        color: selected ? Colors.black : _D.textPrimary, fontSize: 13,
      )),
      selected: selected,
      selectedColor: _D.gold,
      backgroundColor: _D.bgElevated,
      onSelected: (_) {
        setState(() {
          _dojoContext = value;
          _dojoMethods = [];
        });
        if (value != null) _loadDojoMethods(value);
      },
    );
  }

  Widget _typeRadio(String id, String name, {String? subtitle}) {
    return RadioListTile<String>(
      dense: true,
      title: Text(name, style: const TextStyle(color: _D.textPrimary, fontSize: 14)),
      subtitle: subtitle != null
          ? Text(subtitle, style: const TextStyle(color: _D.textSecondary, fontSize: 11))
          : null,
      value: id,
      groupValue: _sessionType,
      activeColor: _D.gold,
      onChanged: (v) => setState(() => _sessionType = v ?? _sessionType),
    );
  }

  Widget _buildJoinView() {
    final sessionIdController = TextEditingController();
    return Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const Icon(Icons.group_work, color: _D.gold, size: 64),
          const SizedBox(height: 24),
          const Text('JOIN TRAINING SESSION',
              style: TextStyle(color: _D.gold, fontSize: 18, fontWeight: FontWeight.bold,
                  fontFamily: 'Cormorant Garamond', letterSpacing: 2)),
          const SizedBox(height: 8),
          const Text('Enter the session ID provided by your master coach',
              style: TextStyle(color: _D.textSecondary), textAlign: TextAlign.center),
          const SizedBox(height: 24),
          TextField(
            controller: sessionIdController,
            style: const TextStyle(color: _D.textPrimary),
            decoration: const InputDecoration(
              labelText: 'Session ID',
              labelStyle: TextStyle(color: _D.textSecondary),
              prefixIcon: Icon(Icons.key, color: _D.goldDim),
              enabledBorder: OutlineInputBorder(borderSide: BorderSide(color: _D.goldDim)),
              focusedBorder: OutlineInputBorder(borderSide: BorderSide(color: _D.gold)),
            ),
          ),
          const SizedBox(height: 20),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton.icon(
              style: ElevatedButton.styleFrom(
                backgroundColor: _D.gold,
                padding: const EdgeInsets.symmetric(vertical: 16),
              ),
              onPressed: _isLoading
                  ? null
                  : () => _joinSession(sessionIdController.text.trim()),
              icon: _isLoading
                  ? const SizedBox(width: 20, height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black))
                  : const Icon(Icons.login, color: Colors.black),
              label: Text(_isLoading ? 'Joining...' : 'Join Session',
                  style: const TextStyle(color: Colors.black, fontWeight: FontWeight.bold)),
            ),
          ),
          if (!kIsWeb) ...[
            const SizedBox(height: 32),
            const Divider(color: _D.goldDim),
            const SizedBox(height: 16),
            const Text('Or scan for nearby sessions',
                style: TextStyle(color: _D.textSecondary, fontSize: 13)),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              style: OutlinedButton.styleFrom(side: const BorderSide(color: _D.cyan)),
              onPressed: _startBleDiscovery,
              icon: const Icon(Icons.bluetooth_searching, color: _D.cyan),
              label: const Text('Scan BLE', style: TextStyle(color: _D.cyan)),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildDiscoveringView() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (!_discoveryTimedOut) ...[
              const CircularProgressIndicator(color: _D.cyan),
              const SizedBox(height: 20),
              const Text('Scanning for nearby Coach devices...',
                  style: TextStyle(color: _D.textSecondary)),
            ] else ...[
              const Icon(Icons.bluetooth_disabled, color: _D.goldDim, size: 48),
              const SizedBox(height: 16),
              const Text('No nearby sessions found',
                  style: TextStyle(color: _D.gold, fontSize: 16, fontFamily: 'Cormorant Garamond')),
              const SizedBox(height: 8),
              const Text(
                'No coaching sessions are broadcasting nearby.\nAsk your coach for the Session ID and use "Join Session" instead.',
                textAlign: TextAlign.center,
                style: TextStyle(color: _D.textSecondary, fontSize: 13, height: 1.5),
              ),
            ],
            const SizedBox(height: 24),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                OutlinedButton(
                  onPressed: () {
                    _discoveryTimer?.cancel();
                    setState(() => _state = CoachingMeshState.IDLE);
                  },
                  child: Text(
                    _discoveryTimedOut ? 'Back' : 'Cancel',
                    style: TextStyle(color: _discoveryTimedOut ? _D.gold : _D.red),
                  ),
                ),
                if (_discoveryTimedOut) ...[
                  const SizedBox(width: 12),
                  OutlinedButton.icon(
                    style: OutlinedButton.styleFrom(side: const BorderSide(color: _D.cyan)),
                    onPressed: _startBleDiscovery,
                    icon: const Icon(Icons.refresh, color: _D.cyan, size: 18),
                    label: const Text('Retry', style: TextStyle(color: _D.cyan)),
                  ),
                ],
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildActiveView() {
    return Column(
      children: [
        if (_isTimed && _remainingSeconds > 0)
          Container(
            padding: const EdgeInsets.symmetric(vertical: 6),
            color: _D.red.withOpacity(0.2),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(Icons.timer, color: _D.red, size: 18),
                const SizedBox(width: 8),
                Text(
                  '${(_remainingSeconds ~/ 60).toString().padLeft(2, '0')}:${(_remainingSeconds % 60).toString().padLeft(2, '0')}',
                  style: const TextStyle(color: _D.red, fontSize: 18, fontWeight: FontWeight.bold),
                ),
              ],
            ),
          ),
        TabBar(
          controller: _tabController,
          indicatorColor: _D.gold,
          labelColor: _D.gold,
          unselectedLabelColor: _D.textSecondary,
          tabs: const [
            Tab(icon: Icon(Icons.chat_bubble_outline, size: 18), text: 'Discussion'),
            Tab(icon: Icon(Icons.quiz, size: 18), text: 'Quiz'),
            Tab(icon: Icon(Icons.theater_comedy, size: 18), text: 'Scenario'),
          ],
        ),
        Expanded(
          child: TabBarView(
            controller: _tabController,
            children: [
              _buildDiscussionTab(),
              _buildQuizTab(),
              _buildScenarioTab(),
            ],
          ),
        ),
      ],
    );
  }

  // ── Discussion Tab ──

  Widget _buildDiscussionTab() {
    return Column(
      children: [
        Expanded(
          child: _messages.isEmpty
              ? Center(
                  child: Text(
                    _nateParticipation ? 'Type @nate to ask Little Nate' : 'Start the discussion...',
                    style: const TextStyle(color: _D.textSecondary),
                  ),
                )
              : ListView.builder(
                  controller: _scrollController,
                  padding: const EdgeInsets.all(12),
                  itemCount: _messages.length,
                  itemBuilder: (_, i) => _buildMessageBubble(_messages[i]),
                ),
        ),
        _buildChatInput(),
      ],
    );
  }

  Widget _buildMessageBubble(MeshChatMessage msg) {
    final isMe = msg.senderId == (widget.profile['hardware_id'] ?? '');
    final isSystem = msg.type == 'system';
    final isNate = msg.isNate;

    if (isSystem) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Center(
          child: Text(msg.content,
              style: const TextStyle(color: _D.textSecondary, fontSize: 12, fontStyle: FontStyle.italic)),
        ),
      );
    }

    return Align(
      alignment: isMe ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.all(12),
        constraints: const BoxConstraints(maxWidth: 320),
        decoration: BoxDecoration(
          color: isNate ? _D.cyan.withOpacity(0.15) : (isMe ? _D.gold.withOpacity(0.15) : _D.bgElevated),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: isNate ? _D.cyan.withOpacity(0.3) : (isMe ? _D.gold.withOpacity(0.3) : Colors.transparent),
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (isNate) const Icon(Icons.psychology, color: _D.cyan, size: 14),
                if (isNate) const SizedBox(width: 4),
                Text(
                  isNate ? 'Little Nate' : msg.senderName,
                  style: TextStyle(
                    color: isNate ? _D.cyan : _D.gold,
                    fontSize: 11,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(msg.content, style: const TextStyle(color: _D.textPrimary, fontSize: 14)),
            if (msg.score != null) ...[
              const SizedBox(height: 6),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: _D.gold.withOpacity(0.2),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text('Score: ${msg.score!.toStringAsFixed(2)}',
                    style: const TextStyle(color: _D.gold, fontSize: 11, fontWeight: FontWeight.bold)),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildChatInput() {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: const BoxDecoration(
        color: _D.bgChamber,
        border: Border(top: BorderSide(color: _D.goldDim, width: 0.5)),
      ),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _chatController,
              style: const TextStyle(color: _D.textPrimary),
              decoration: const InputDecoration(
                hintText: 'Type a message... (@nate for AI)',
                hintStyle: TextStyle(color: _D.textSecondary, fontSize: 13),
                border: InputBorder.none,
                contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              ),
              onSubmitted: (_) => _sendMessage(),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.send, color: _D.gold),
            onPressed: _sendMessage,
          ),
        ],
      ),
    );
  }

  // ── Quiz Tab ──

  Widget _buildQuizTab() {
    if (_quizQuestions.isEmpty) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.quiz, color: _D.goldDim, size: 48),
            const SizedBox(height: 12),
            Text(
              widget.isMaster ? 'Push questions to the group' : 'Waiting for quiz questions...',
              style: const TextStyle(color: _D.textSecondary),
            ),
            if (widget.isMaster) ...[
              const SizedBox(height: 16),
              ElevatedButton.icon(
                style: ElevatedButton.styleFrom(backgroundColor: _D.gold),
                onPressed: _showPushQuizDialog,
                icon: const Icon(Icons.add, color: Colors.black),
                label: const Text('Push Questions', style: TextStyle(color: Colors.black)),
              ),
            ],
          ],
        ),
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.all(12),
      itemCount: _quizQuestions.length + (widget.isMaster ? 1 : 0),
      itemBuilder: (_, i) {
        if (widget.isMaster && i == _quizQuestions.length) {
          return Padding(
            padding: const EdgeInsets.only(top: 16),
            child: ElevatedButton.icon(
              style: ElevatedButton.styleFrom(backgroundColor: _D.gold),
              onPressed: _showPushQuizDialog,
              icon: const Icon(Icons.add, color: Colors.black),
              label: const Text('Push More Questions', style: TextStyle(color: Colors.black)),
            ),
          );
        }
        return _buildQuizCard(_quizQuestions[i]);
      },
    );
  }

  Widget _buildQuizCard(MeshQuizQuestion q) {
    final answerController = TextEditingController(text: q.selectedAnswer);
    return Card(
      color: _D.bgElevated,
      margin: const EdgeInsets.only(bottom: 12),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(
          color: q.submitted
              ? (q.score != null && q.score! >= 0.7 ? _D.green : _D.gold)
              : _D.goldDim,
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Question ${q.index + 1}',
                style: const TextStyle(color: _D.gold, fontSize: 12, fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            Text(q.text, style: const TextStyle(color: _D.textPrimary, fontSize: 15)),
            const SizedBox(height: 12),

            if (q.options != null && q.options!.isNotEmpty)
              ...q.options!.map((opt) => RadioListTile<String>(
                    dense: true,
                    title: Text(opt, style: const TextStyle(color: _D.textPrimary, fontSize: 13)),
                    value: opt,
                    groupValue: q.selectedAnswer,
                    activeColor: _D.gold,
                    onChanged: q.submitted
                        ? null
                        : (v) => setState(() => q.selectedAnswer = v),
                  ))
            else
              TextField(
                controller: answerController,
                enabled: !q.submitted,
                style: const TextStyle(color: _D.textPrimary),
                maxLines: 3,
                decoration: const InputDecoration(
                  hintText: 'Your answer...',
                  hintStyle: TextStyle(color: _D.textSecondary),
                  enabledBorder: OutlineInputBorder(borderSide: BorderSide(color: _D.goldDim)),
                ),
                onChanged: (v) => q.selectedAnswer = v,
              ),

            const SizedBox(height: 12),

            if (!q.submitted)
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  style: ElevatedButton.styleFrom(backgroundColor: _D.gold),
                  onPressed: () {
                    final answer = q.selectedAnswer ?? answerController.text;
                    if (answer.isNotEmpty) _submitQuizAnswer(q.index, answer);
                  },
                  child: const Text('Submit', style: TextStyle(color: Colors.black)),
                ),
              ),

            if (q.submitted && q.score != null) ...[
              const Divider(color: _D.goldDim, height: 20),
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                    decoration: BoxDecoration(
                      color: q.score! >= 0.7
                          ? _D.green.withOpacity(0.2)
                          : _D.gold.withOpacity(0.2),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Text(
                      'Score: ${(q.score! * 100).toStringAsFixed(0)}%',
                      style: TextStyle(
                        color: q.score! >= 0.7 ? _D.green : _D.gold,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ],
              ),
              if (q.feedback != null) ...[
                const SizedBox(height: 8),
                Text(q.feedback!, style: const TextStyle(color: _D.textSecondary, fontSize: 13)),
              ],
            ],
          ],
        ),
      ),
    );
  }

  // ── Scenario Tab ──

  Widget _buildScenarioTab() {
    if (_scenarioDescription == null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.theater_comedy, color: _D.goldDim, size: 48),
            const SizedBox(height: 12),
            Text(
              widget.isMaster ? 'Push a scenario to the group' : 'Waiting for scenario...',
              style: const TextStyle(color: _D.textSecondary),
            ),
            if (widget.isMaster) ...[
              const SizedBox(height: 16),
              ElevatedButton.icon(
                style: ElevatedButton.styleFrom(backgroundColor: _D.purple),
                onPressed: _showPushScenarioDialog,
                icon: const Icon(Icons.add, color: Colors.white),
                label: const Text('Push Scenario', style: TextStyle(color: Colors.white)),
              ),
            ],
          ],
        ),
      );
    }

    final responseController = TextEditingController();
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: _D.purple.withOpacity(0.1),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: _D.purple.withOpacity(0.3)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Icon(Icons.theater_comedy, color: _D.purple, size: 18),
                    const SizedBox(width: 8),
                    Text('${_dojoLabels[_scenarioDojoType] ?? 'Scenario'} Practice',
                        style: const TextStyle(color: _D.purple, fontWeight: FontWeight.bold)),
                  ],
                ),
                const SizedBox(height: 12),
                Text(_scenarioDescription!,
                    style: const TextStyle(color: _D.textPrimary, fontSize: 15)),
              ],
            ),
          ),
          const SizedBox(height: 20),
          if (!widget.isMaster) ...[
            const Text('YOUR RESPONSE', style: TextStyle(color: _D.textSecondary, fontSize: 12)),
            const SizedBox(height: 8),
            TextField(
              controller: responseController,
              style: const TextStyle(color: _D.textPrimary),
              maxLines: 6,
              decoration: const InputDecoration(
                hintText: 'Write your response to the scenario...',
                hintStyle: TextStyle(color: _D.textSecondary),
                enabledBorder: OutlineInputBorder(borderSide: BorderSide(color: _D.goldDim)),
                focusedBorder: OutlineInputBorder(borderSide: BorderSide(color: _D.purple)),
              ),
            ),
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                style: ElevatedButton.styleFrom(backgroundColor: _D.purple),
                onPressed: () {
                  if (responseController.text.isNotEmpty) {
                    _wsChannel?.sink.add(jsonEncode({
                      'type': 'coaching_mesh_answer',
                      'session_id': _sessionId,
                      'question_index': 0,
                      'answer': responseController.text,
                    }));
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('Response submitted'), backgroundColor: _D.purple),
                    );
                  }
                },
                child: const Text('Submit Response', style: TextStyle(color: Colors.white)),
              ),
            ),
          ],
          if (widget.isMaster) ...[
            const SizedBox(height: 16),
            ElevatedButton.icon(
              style: ElevatedButton.styleFrom(backgroundColor: _D.purple),
              onPressed: _showPushScenarioDialog,
              icon: const Icon(Icons.refresh, color: Colors.white),
              label: const Text('Push New Scenario', style: TextStyle(color: Colors.white)),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildClosingView() {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.check_circle, color: _D.green, size: 64),
          const SizedBox(height: 16),
          const Text('Session Complete',
              style: TextStyle(color: _D.gold, fontSize: 20, fontFamily: 'Cormorant Garamond')),
          const SizedBox(height: 8),
          Text('${_participants.length} participants | ${_messages.length} messages',
              style: const TextStyle(color: _D.textSecondary)),
          const SizedBox(height: 24),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: _D.gold),
            onPressed: () => Navigator.pop(context),
            child: const Text('Close', style: TextStyle(color: Colors.black)),
          ),
        ],
      ),
    );
  }

  void _showParticipantsSheet() {
    showModalBottomSheet(
      context: context,
      backgroundColor: _D.bgElevated,
      builder: (_) => Container(
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Participants (${_participants.length})',
                style: const TextStyle(color: _D.gold, fontSize: 16, fontWeight: FontWeight.bold)),
            const Divider(color: _D.goldDim),
            ..._participants.map((p) => ListTile(
                  leading: CircleAvatar(
                    backgroundColor: p.role == 'master'
                        ? _D.gold.withOpacity(0.2)
                        : _D.cyan.withOpacity(0.2),
                    child: Icon(
                      p.role == 'master' ? Icons.star : Icons.person,
                      color: p.role == 'master' ? _D.gold : _D.cyan,
                      size: 18,
                    ),
                  ),
                  title: Text(p.username, style: const TextStyle(color: _D.textPrimary)),
                  subtitle: Text(p.role.toUpperCase(),
                      style: TextStyle(color: p.role == 'master' ? _D.gold : _D.cyan, fontSize: 11)),
                  trailing: Icon(Icons.circle,
                      color: p.connected ? _D.green : _D.red, size: 10),
                )),
          ],
        ),
      ),
    );
  }
}
