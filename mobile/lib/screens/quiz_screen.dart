// =============================================================================
// QUIZ / ASSESSMENTS SCREEN — Client interactive assessments
// REST API: GET /api/quizzes, GET /api/quizzes/{id}, POST /api/quizzes/{id}/submit
// =============================================================================

import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import '../config/app_config.dart';

class _D {
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
}

class _AssessmentTheme {
  final IconData icon;
  final Color accent;
  final String subtitle;

  const _AssessmentTheme({required this.icon, required this.accent, required this.subtitle});
}

const Map<String, _AssessmentTheme> _assessmentThemes = {
  'the mirror': _AssessmentTheme(
    icon: Icons.auto_awesome,
    accent: Color(0xFFC9A962),
    subtitle: 'Self-Reflection & Awareness',
  ),
  'the bridge': _AssessmentTheme(
    icon: Icons.handshake_outlined,
    accent: Color(0xFF4ECDC4),
    subtitle: 'Connection & Relationship',
  ),
  'the voice inside': _AssessmentTheme(
    icon: Icons.record_voice_over,
    accent: Color(0xFF9D4EDD),
    subtitle: 'Inner Voice & Self-Talk',
  ),
  'the compass': _AssessmentTheme(
    icon: Icons.explore_outlined,
    accent: Color(0xFF3B82F6),
    subtitle: 'Direction & Purpose',
  ),
  'the threshold': _AssessmentTheme(
    icon: Icons.door_front_door_outlined,
    accent: Color(0xFFFF8C42),
    subtitle: 'Growth & Readiness',
  ),
};

_AssessmentTheme _themeFor(String? title) {
  final key = (title ?? '').toLowerCase().trim();
  return _assessmentThemes[key] ??
      const _AssessmentTheme(icon: Icons.assignment, accent: _D.gold, subtitle: 'Assessment');
}

class QuizScreen extends StatefulWidget {
  final Map<String, dynamic>? profile;
  const QuizScreen({super.key, this.profile});

  @override
  State<QuizScreen> createState() => _QuizScreenState();
}

class _QuizScreenState extends State<QuizScreen> {
  List<dynamic> _quizzes = [];
  Map<String, dynamic>? _activeQuiz;
  List<dynamic> _questions = [];
  final Map<int, dynamic> _answers = {};
  int _currentIndex = 0;
  bool _loading = true;
  bool _submitting = false;
  Map<String, dynamic>? _resultData;
  final Set<String> _completedIds = {};

  String get _baseUrl => AppConfig.apiBaseUrl;
  String? get _token => widget.profile?['token'] as String?;
  Map<String, String> get _authHeaders => {
    'Content-Type': 'application/json',
    if (_token != null && _token!.isNotEmpty) 'Authorization': 'Bearer $_token',
  };

  final Map<String, double?> _completionScores = {};

  @override
  void initState() {
    super.initState();
    _loadQuizzes();
  }

  Future<void> _loadQuizzes() async {
    setState(() => _loading = true);
    try {
      final res = await http.get(
        Uri.parse('$_baseUrl/api/quizzes'),
        headers: _authHeaders,
      );
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        setState(() => _quizzes = data is List ? data : data['quizzes'] ?? []);
      } else {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('Could not load assessments (${res.statusCode}). Please try again.'),
              backgroundColor: _D.red,
            ),
          );
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error loading assessments: $e'), backgroundColor: _D.red),
        );
      }
    }
    await _loadCompletions();
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _loadCompletions() async {
    final userId = widget.profile?['hardware_id'] ?? widget.profile?['id'] ?? '';
    if (userId.toString().isEmpty) return;
    try {
      final res = await http.get(
        Uri.parse('$_baseUrl/api/quizzes/completions/$userId'),
        headers: _authHeaders,
      );
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        if (data is List) {
          for (final item in data) {
            final qid = item['quiz_id']?.toString() ?? '';
            if (qid.isNotEmpty) {
              _completedIds.add(qid);
              final score = item['score'];
              if (score != null) _completionScores[qid] = (score as num).toDouble();
            }
          }
          if (mounted) setState(() {});
        }
      }
    } catch (_) {}
  }

  Future<void> _loadQuiz(dynamic quiz) async {
    final quizId = quiz['id'];
    setState(() { _loading = true; _resultData = null; });
    try {
      final res = await http.get(
        Uri.parse('$_baseUrl/api/quizzes/$quizId'),
        headers: _authHeaders,
      );
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        setState(() {
          _activeQuiz = data;
          _questions = data['questions'] ?? [];
          _answers.clear();
          _currentIndex = 0;
        });
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error: $e'), backgroundColor: _D.red),
        );
      }
    }
    if (mounted) setState(() => _loading = false);
  }

  void _submitQuiz() async {
    setState(() => _submitting = true);
    final quizId = _activeQuiz?['id'] ?? _activeQuiz?['quiz_id'] ?? '';
    final userId = widget.profile?['hardware_id'] ?? widget.profile?['id'] ?? '';
    try {
      final response = await http.post(
        Uri.parse('$_baseUrl/api/quizzes/$quizId/submit'),
        headers: _authHeaders,
        body: jsonEncode({
          'quiz_id': quizId,
          'user_id': userId,
          'answers': _answers.map((k, v) => MapEntry(k.toString(), v)),
        }),
      );
      if (mounted) {
        setState(() => _submitting = false);
        if (response.statusCode == 200 || response.statusCode == 201) {
          Map<String, dynamic>? result;
          try { result = jsonDecode(response.body) as Map<String, dynamic>; } catch (_) {}
          setState(() {
            _completedIds.add(quizId.toString());
            _resultData = result;
          });
        } else {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Submission failed (${response.statusCode}). Please try again.'), backgroundColor: _D.red),
          );
        }
      }
    } catch (e) {
      if (mounted) {
        setState(() => _submitting = false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error submitting: $e'), backgroundColor: _D.red),
        );
      }
    }
  }

  void _backToList() {
    setState(() {
      _activeQuiz = null;
      _questions = [];
      _answers.clear();
      _resultData = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    final title = _activeQuiz != null ? (_activeQuiz!['title'] ?? 'Assessment') : 'Assessments';
    final theme = _themeFor(_activeQuiz?['title']);

    return Scaffold(
      backgroundColor: _D.bgVoid,
      appBar: AppBar(
        backgroundColor: _D.bgChamber,
        title: Text(
          title,
          style: TextStyle(
            color: _activeQuiz != null ? theme.accent : _D.gold,
            fontSize: 16,
            fontFamily: 'Cormorant Garamond',
            fontWeight: FontWeight.bold,
          ),
        ),
        iconTheme: IconThemeData(color: _activeQuiz != null ? theme.accent : _D.gold),
        leading: _activeQuiz != null
          ? IconButton(icon: const Icon(Icons.arrow_back), onPressed: _backToList)
          : null,
      ),
      body: _loading
        ? const Center(child: CircularProgressIndicator(color: _D.gold))
        : _resultData != null
          ? _buildResultView()
          : _activeQuiz != null
            ? _buildQuizView()
            : _buildQuizList(),
    );
  }

  // ─── QUIZ LIST ──────────────────────────────────────────────────────────

  Widget _buildQuizList() {
    if (_quizzes.isEmpty) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.self_improvement, color: _D.gold.withOpacity(0.4), size: 64),
            const SizedBox(height: 16),
            const Text('No assessments available yet',
                style: TextStyle(color: _D.textSecondary, fontFamily: 'DM Sans', fontSize: 15)),
            const SizedBox(height: 8),
            const Text('Check back soon — your journey is unfolding.',
                style: TextStyle(color: _D.goldDim, fontFamily: 'DM Sans', fontSize: 12)),
          ],
        ),
      );
    }

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Padding(
          padding: const EdgeInsets.only(bottom: 20),
          child: Text(
            'Your Assessments',
            style: TextStyle(
              color: _D.goldBright,
              fontSize: 22,
              fontFamily: 'Cormorant Garamond',
              fontWeight: FontWeight.bold,
            ),
          ),
        ),
        ..._quizzes.map((q) => _buildAssessmentCard(q)),
      ],
    );
  }

  Widget _buildAssessmentCard(dynamic q) {
    final title = q['title']?.toString() ?? 'Untitled';
    final description = q['description']?.toString();
    final theme = _themeFor(title);
    final qId = q['id']?.toString() ?? '';
    final isComplete = _completedIds.contains(qId);
    final priorScore = _completionScores[qId];
    final questionCount = q['question_count'] ?? q['questions_count'];

    return Container(
      margin: const EdgeInsets.only(bottom: 14),
      decoration: BoxDecoration(
        color: _D.bgElevated,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: isComplete ? _D.green.withOpacity(0.4) : theme.accent.withOpacity(0.2)),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: () => _loadQuiz(q),
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Row(
            children: [
              Container(
                width: 52, height: 52,
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topLeft, end: Alignment.bottomRight,
                    colors: [theme.accent.withOpacity(0.2), theme.accent.withOpacity(0.05)],
                  ),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: theme.accent.withOpacity(0.3)),
                ),
                child: Icon(theme.icon, color: theme.accent, size: 26),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(title,
                            style: TextStyle(color: theme.accent, fontWeight: FontWeight.bold, fontSize: 15, fontFamily: 'Cormorant Garamond')),
                        ),
                        if (isComplete)
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                            decoration: BoxDecoration(
                              color: _D.green.withOpacity(0.15),
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                const Icon(Icons.check_circle, color: _D.green, size: 13),
                                const SizedBox(width: 4),
                                Text(
                                  priorScore != null ? '${priorScore.toInt()}%' : 'Done',
                                  style: const TextStyle(color: _D.green, fontSize: 10, fontWeight: FontWeight.bold),
                                ),
                              ],
                            ),
                          ),
                      ],
                    ),
                    const SizedBox(height: 3),
                    Text(theme.subtitle,
                      style: TextStyle(color: theme.accent.withOpacity(0.6), fontSize: 11, fontFamily: 'DM Sans')),
                    if (description != null) ...[
                      const SizedBox(height: 6),
                      Text(description,
                        style: const TextStyle(color: _D.textSecondary, fontSize: 12, fontFamily: 'DM Sans'),
                        maxLines: 2, overflow: TextOverflow.ellipsis),
                    ],
                    if (questionCount != null) ...[
                      const SizedBox(height: 6),
                      Text('$questionCount questions',
                        style: TextStyle(color: _D.goldDim, fontSize: 11, fontFamily: 'DM Sans')),
                    ],
                  ],
                ),
              ),
              Icon(Icons.chevron_right, color: theme.accent.withOpacity(0.5)),
            ],
          ),
        ),
      ),
    );
  }

  // ─── QUIZ VIEW (active) ─────────────────────────────────────────────────

  Widget _buildQuizView() {
    if (_questions.isEmpty) {
      return const Center(child: Text('No questions in this assessment.', style: TextStyle(color: _D.textSecondary)));
    }

    final q = _questions[_currentIndex];
    final type = q['question_type'] ?? 'open_text';
    final progress = (_currentIndex + 1) / _questions.length;
    final theme = _themeFor(_activeQuiz?['title']);

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
          child: Column(
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text('Question ${_currentIndex + 1} of ${_questions.length}',
                    style: const TextStyle(color: _D.textSecondary, fontSize: 12, fontFamily: 'DM Sans')),
                  Text('${(progress * 100).toInt()}%',
                    style: TextStyle(color: theme.accent, fontSize: 12, fontWeight: FontWeight.bold, fontFamily: 'DM Sans')),
                ],
              ),
              const SizedBox(height: 8),
              ClipRRect(
                borderRadius: BorderRadius.circular(4),
                child: LinearProgressIndicator(
                  value: progress,
                  minHeight: 6,
                  backgroundColor: _D.bgElevated,
                  valueColor: AlwaysStoppedAnimation<Color>(theme.accent),
                ),
              ),
            ],
          ),
        ),

        Expanded(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  padding: const EdgeInsets.all(20),
                  decoration: BoxDecoration(
                    color: _D.bgElevated,
                    borderRadius: BorderRadius.circular(14),
                    border: Border.all(color: theme.accent.withOpacity(0.15)),
                  ),
                  child: Text(
                    q['question_text'] ?? '',
                    style: const TextStyle(color: _D.textPrimary, fontSize: 16, fontWeight: FontWeight.w500, fontFamily: 'DM Sans', height: 1.5),
                  ),
                ),
                const SizedBox(height: 24),
                if (type == 'scale') _buildScaleQuestion(q, theme),
                if (type == 'multiple_choice') _buildMultipleChoiceQuestion(q, theme),
                if (type == 'multi_select') _buildMultiSelectQuestion(q, theme),
                if (type == 'open_text') _buildOpenTextQuestion(q, theme),
                if (type == 'ranking') _buildMultipleChoiceQuestion(q, theme),
              ],
            ),
          ),
        ),

        Container(
          color: _D.bgChamber,
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 20),
          child: Row(
            children: [
              if (_currentIndex > 0)
                OutlinedButton(
                  style: OutlinedButton.styleFrom(side: BorderSide(color: theme.accent.withOpacity(0.5))),
                  onPressed: () => setState(() => _currentIndex--),
                  child: Text('Back', style: TextStyle(color: theme.accent)),
                ),
              const Spacer(),
              if (_currentIndex < _questions.length - 1)
                ElevatedButton(
                  style: ElevatedButton.styleFrom(backgroundColor: theme.accent),
                  onPressed: () => setState(() => _currentIndex++),
                  child: const Text('Next', style: TextStyle(color: Colors.black)),
                )
              else
                ElevatedButton(
                  style: ElevatedButton.styleFrom(backgroundColor: _D.green),
                  onPressed: _submitting ? null : _submitQuiz,
                  child: _submitting
                    ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(color: Colors.black, strokeWidth: 2))
                    : const Text('Submit', style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold)),
                ),
            ],
          ),
        ),
      ],
    );
  }

  // ─── RESULT VIEW ────────────────────────────────────────────────────────

  Widget _buildResultView() {
    final theme = _themeFor(_activeQuiz?['title']);
    final title = _activeQuiz?['title'] ?? 'Assessment';
    final score = _resultData?['score'];
    final insights = _resultData?['insights'] ?? _resultData?['analysis'] ?? _resultData?['feedback'];
    final answeredCount = _resultData?['answered'] ?? _answers.length;
    final totalQuestions = _resultData?['total_questions'] ?? _questions.length;
    final dimensionScores = _resultData?['dimension_scores'] as Map<String, dynamic>? ?? {};

    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        children: [
          const SizedBox(height: 20),
          Container(
            width: 80, height: 80,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              gradient: RadialGradient(
                colors: [theme.accent.withOpacity(0.3), theme.accent.withOpacity(0.05)],
              ),
              border: Border.all(color: theme.accent.withOpacity(0.4), width: 2),
            ),
            child: Icon(Icons.check_circle_outline, color: theme.accent, size: 42),
          ),
          const SizedBox(height: 20),
          Text(title,
            style: TextStyle(color: theme.accent, fontSize: 22, fontFamily: 'Cormorant Garamond', fontWeight: FontWeight.bold)),
          const SizedBox(height: 6),
          Text('Complete — $answeredCount of $totalQuestions answered', style: const TextStyle(color: _D.green, fontSize: 14, fontFamily: 'DM Sans', fontWeight: FontWeight.w600)),
          const SizedBox(height: 24),

          if (score != null)
            Container(
              padding: const EdgeInsets.all(20),
              margin: const EdgeInsets.only(bottom: 16),
              decoration: BoxDecoration(
                color: _D.bgElevated,
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: theme.accent.withOpacity(0.2)),
              ),
              child: Column(
                children: [
                  const Text('Overall Score', style: TextStyle(color: _D.textSecondary, fontSize: 12, fontFamily: 'DM Sans')),
                  const SizedBox(height: 8),
                  Text('$score%', style: TextStyle(color: theme.accent, fontSize: 36, fontFamily: 'Cormorant Garamond', fontWeight: FontWeight.bold)),
                ],
              ),
            ),

          if (dimensionScores.isNotEmpty)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(20),
              margin: const EdgeInsets.only(bottom: 16),
              decoration: BoxDecoration(
                color: _D.bgElevated,
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: Colors.white10),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(Icons.insights, color: theme.accent, size: 18),
                      const SizedBox(width: 8),
                      Text('Dimension Breakdown', style: TextStyle(color: theme.accent, fontSize: 14, fontWeight: FontWeight.bold, fontFamily: 'DM Sans')),
                    ],
                  ),
                  const SizedBox(height: 14),
                  ...dimensionScores.entries.map((e) {
                    final dimLabel = e.key.replaceAll('_', ' ');
                    final dimVal = (e.value is num) ? (e.value as num).toDouble() : 0.0;
                    final barColor = dimVal >= 70 ? _D.green : dimVal >= 40 ? _D.gold : _D.red;
                    return Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              Text(dimLabel[0].toUpperCase() + dimLabel.substring(1),
                                style: const TextStyle(color: _D.textPrimary, fontSize: 12, fontFamily: 'DM Sans')),
                              Text('${dimVal.toInt()}%',
                                style: TextStyle(color: barColor, fontSize: 12, fontWeight: FontWeight.bold, fontFamily: 'DM Sans')),
                            ],
                          ),
                          const SizedBox(height: 4),
                          ClipRRect(
                            borderRadius: BorderRadius.circular(3),
                            child: LinearProgressIndicator(
                              value: (dimVal / 100).clamp(0.0, 1.0),
                              minHeight: 6,
                              backgroundColor: _D.bgChamber,
                              valueColor: AlwaysStoppedAnimation<Color>(barColor),
                            ),
                          ),
                        ],
                      ),
                    );
                  }),
                ],
              ),
            ),

          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(20),
            margin: const EdgeInsets.only(bottom: 16),
            decoration: BoxDecoration(
              color: _D.bgElevated,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: Colors.white10),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(Icons.analytics_outlined, color: theme.accent, size: 18),
                    const SizedBox(width: 8),
                    Text('Summary', style: TextStyle(color: theme.accent, fontSize: 14, fontWeight: FontWeight.bold, fontFamily: 'DM Sans')),
                  ],
                ),
                const SizedBox(height: 12),
                if (insights is String && insights.isNotEmpty)
                  Text(insights, style: const TextStyle(color: _D.textPrimary, fontSize: 13, fontFamily: 'DM Sans', height: 1.6))
                else if (insights is Map)
                  ...((insights as Map).entries.map((e) => Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: RichText(
                      text: TextSpan(children: [
                        TextSpan(text: '${e.key}: ', style: TextStyle(color: theme.accent, fontSize: 13, fontWeight: FontWeight.w600)),
                        TextSpan(text: '${e.value}', style: const TextStyle(color: _D.textPrimary, fontSize: 13)),
                      ]),
                    ),
                  )))
                else
                  Text(
                    'You answered $answeredCount of ${_questions.length} questions. '
                    'Your responses have been recorded and will inform Little Nate\'s understanding of your journey.',
                    style: const TextStyle(color: _D.textPrimary, fontSize: 13, fontFamily: 'DM Sans', height: 1.6),
                  ),
              ],
            ),
          ),

          const SizedBox(height: 8),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              style: ElevatedButton.styleFrom(
                backgroundColor: theme.accent,
                padding: const EdgeInsets.symmetric(vertical: 14),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              ),
              onPressed: _backToList,
              child: const Text('Back to Assessments', style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold, fontSize: 14)),
            ),
          ),
        ],
      ),
    );
  }

  // ─── QUESTION TYPES ─────────────────────────────────────────────────────

  List<Map<String, dynamic>> _parseOptions(dynamic raw) {
    if (raw is List) {
      return raw.whereType<Map<String, dynamic>>().toList();
    }
    if (raw is String && raw.isNotEmpty) {
      try {
        final parsed = jsonDecode(raw);
        if (parsed is List) return parsed.whereType<Map<String, dynamic>>().toList();
      } catch (_) {}
    }
    return [];
  }

  Widget _buildScaleQuestion(Map<String, dynamic> q, _AssessmentTheme theme) {
    final min = (q['scale_min'] ?? 1).toDouble();
    final max = (q['scale_max'] ?? 10).toDouble();
    final current = (_answers[_currentIndex] ?? ((min + max) / 2)).toDouble();
    return Column(
      children: [
        Slider(
          value: current.clamp(min, max),
          min: min,
          max: max,
          divisions: (max - min).toInt(),
          activeColor: theme.accent,
          inactiveColor: _D.bgElevated,
          label: current.toInt().toString(),
          onChanged: (v) => setState(() => _answers[_currentIndex] = v),
        ),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(q['scale_min_label'] ?? min.toInt().toString(),
              style: const TextStyle(color: _D.textSecondary, fontSize: 11, fontFamily: 'DM Sans')),
            Text(current.toInt().toString(),
              style: TextStyle(color: theme.accent, fontSize: 18, fontWeight: FontWeight.bold)),
            Text(q['scale_max_label'] ?? max.toInt().toString(),
              style: const TextStyle(color: _D.textSecondary, fontSize: 11, fontFamily: 'DM Sans')),
          ],
        ),
      ],
    );
  }

  Widget _buildMultipleChoiceQuestion(Map<String, dynamic> q, _AssessmentTheme theme) {
    final options = _parseOptions(q['options']);
    final selected = _answers[_currentIndex];
    return Column(
      children: options.map((opt) {
        final optKey = opt['value'] ?? opt['id'] ?? opt['text'] ?? opt['label'] ?? '';
        final optLabel = opt['label'] ?? opt['text'] ?? opt['value'] ?? '';
        final isSelected = selected == optKey;
        return Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: InkWell(
            borderRadius: BorderRadius.circular(10),
            onTap: () => setState(() => _answers[_currentIndex] = optKey),
            child: Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: isSelected ? theme.accent.withOpacity(0.1) : _D.bgElevated,
                border: Border.all(color: isSelected ? theme.accent : Colors.white10),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Row(
                children: [
                  Icon(isSelected ? Icons.radio_button_checked : Icons.radio_button_off,
                    color: isSelected ? theme.accent : _D.textSecondary, size: 20),
                  const SizedBox(width: 12),
                  Expanded(child: Text(optLabel.toString(),
                    style: TextStyle(color: isSelected ? theme.accent : _D.textPrimary, fontSize: 13, fontFamily: 'DM Sans'))),
                ],
              ),
            ),
          ),
        );
      }).toList(),
    );
  }

  Widget _buildMultiSelectQuestion(Map<String, dynamic> q, _AssessmentTheme theme) {
    final options = _parseOptions(q['options']);
    final selected = (_answers[_currentIndex] as List?) ?? [];
    return Column(
      children: options.map((opt) {
        final key = opt['value'] ?? opt['id'] ?? opt['text'] ?? opt['label'] ?? '';
        final isSelected = selected.contains(key);
        return Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: InkWell(
            borderRadius: BorderRadius.circular(10),
            onTap: () {
              setState(() {
                final list = List.from(selected);
                if (isSelected) { list.remove(key); } else { list.add(key); }
                _answers[_currentIndex] = list;
              });
            },
            child: Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: isSelected ? theme.accent.withOpacity(0.1) : _D.bgElevated,
                border: Border.all(color: isSelected ? theme.accent : Colors.white10),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Row(
                children: [
                  Icon(isSelected ? Icons.check_box : Icons.check_box_outline_blank,
                    color: isSelected ? theme.accent : _D.textSecondary, size: 20),
                  const SizedBox(width: 12),
                  Expanded(child: Text((opt['label'] ?? opt['text'] ?? opt['value'] ?? '').toString(),
                    style: TextStyle(color: isSelected ? theme.accent : _D.textPrimary, fontSize: 13, fontFamily: 'DM Sans'))),
                ],
              ),
            ),
          ),
        );
      }).toList(),
    );
  }

  Widget _buildOpenTextQuestion(Map<String, dynamic> q, _AssessmentTheme theme) {
    return TextField(
      style: const TextStyle(color: _D.textPrimary, fontSize: 13, fontFamily: 'DM Sans'),
      maxLines: 5,
      decoration: InputDecoration(
        hintText: 'Type your response...',
        hintStyle: TextStyle(color: Colors.grey[600]),
        filled: true,
        fillColor: _D.bgElevated,
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: const BorderSide(color: Colors.white10)),
        enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: const BorderSide(color: Colors.white10)),
        focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: theme.accent)),
      ),
      onChanged: (v) => _answers[_currentIndex] = v,
      controller: TextEditingController(text: _answers[_currentIndex]?.toString() ?? ''),
    );
  }
}
