// =============================================================================
// QUIZ / ASSESSMENTS SCREEN — Client interactive assessments
// REST API: GET /api/quizzes, GET /api/quizzes/{id}
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
  static const cyan = Color(0xFF4ECDC4);
  static const purple = Color(0xFF9D4EDD);
  static const green = Color(0xFF00FF88);
  static const red = Color(0xFFEF4444);
  static const textPrimary = Color(0xFFFFFFFF);
  static const textSecondary = Color(0xFF888888);
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

  String get _baseUrl => AppConfig.apiBaseUrl;

  @override
  void initState() {
    super.initState();
    _loadQuizzes();
  }

  Future<void> _loadQuizzes() async {
    setState(() => _loading = true);
    try {
      final res = await http.get(Uri.parse('$_baseUrl/api/quizzes'));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        setState(() => _quizzes = data is List ? data : data['quizzes'] ?? []);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error loading quizzes: $e'), backgroundColor: _D.red),
        );
      }
    }
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _loadQuiz(dynamic quiz) async {
    final quizId = quiz['id'];
    setState(() => _loading = true);
    try {
      final res = await http.get(Uri.parse('$_baseUrl/api/quizzes/$quizId'));
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
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'quiz_id': quizId,
          'user_id': userId,
          'answers': _answers.map((k, v) => MapEntry(k.toString(), v)),
        }),
      );
      if (mounted) {
        setState(() => _submitting = false);
        if (response.statusCode == 200 || response.statusCode == 201) {
          showDialog(
            context: context,
            builder: (ctx) => AlertDialog(
              backgroundColor: _D.bgElevated,
              title: const Text('Assessment Complete', style: TextStyle(color: _D.gold)),
              content: const Text(
                'Thank you for completing this assessment. Your responses have been recorded.',
                style: TextStyle(color: _D.textPrimary, fontSize: 13),
              ),
              actions: [
                TextButton(
                  onPressed: () {
                    Navigator.pop(ctx);
                    setState(() { _activeQuiz = null; _questions = []; _answers.clear(); });
                  },
                  child: const Text('Done', style: TextStyle(color: _D.gold)),
                ),
              ],
            ),
          );
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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _D.bgVoid,
      appBar: AppBar(
        backgroundColor: _D.bgChamber,
        title: Text(
          _activeQuiz != null ? (_activeQuiz!['title'] ?? 'Assessment') : 'Assessments',
          style: const TextStyle(color: _D.gold, fontSize: 16),
        ),
        iconTheme: const IconThemeData(color: _D.gold),
        leading: _activeQuiz != null
          ? IconButton(icon: const Icon(Icons.arrow_back), onPressed: () => setState(() { _activeQuiz = null; _questions = []; }))
          : null,
      ),
      body: _loading
        ? const Center(child: CircularProgressIndicator(color: _D.gold))
        : _activeQuiz != null
          ? _buildQuizView()
          : _buildQuizList(),
    );
  }

  Widget _buildQuizList() {
    if (_quizzes.isEmpty) {
      return const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.quiz, color: _D.gold, size: 48),
            SizedBox(height: 12),
            Text('No assessments available', style: TextStyle(color: _D.textSecondary)),
          ],
        ),
      );
    }
    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: _quizzes.length,
      itemBuilder: (_, i) {
        final q = _quizzes[i];
        return Card(
          color: _D.bgElevated,
          margin: const EdgeInsets.only(bottom: 12),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          child: InkWell(
            borderRadius: BorderRadius.circular(12),
            onTap: () => _loadQuiz(q),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                children: [
                  Container(
                    width: 48, height: 48,
                    decoration: BoxDecoration(
                      color: _D.gold.withOpacity(0.1),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: const Icon(Icons.assignment, color: _D.gold),
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(q['title'] ?? 'Untitled', style: const TextStyle(color: _D.textPrimary, fontWeight: FontWeight.bold, fontSize: 14)),
                        if (q['description'] != null)
                          Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: Text(q['description'], style: const TextStyle(color: _D.textSecondary, fontSize: 12), maxLines: 2, overflow: TextOverflow.ellipsis),
                          ),
                      ],
                    ),
                  ),
                  const Icon(Icons.chevron_right, color: _D.gold),
                ],
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _buildQuizView() {
    if (_questions.isEmpty) {
      return const Center(child: Text('No questions in this assessment.', style: TextStyle(color: _D.textSecondary)));
    }

    final q = _questions[_currentIndex];
    final type = q['question_type'] ?? 'open_text';
    final progress = (_currentIndex + 1) / _questions.length;

    return Column(
      children: [
        // Progress bar
        Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text('Question ${_currentIndex + 1} of ${_questions.length}', style: const TextStyle(color: _D.textSecondary, fontSize: 12)),
                  Text('${(progress * 100).toInt()}%', style: const TextStyle(color: _D.gold, fontSize: 12, fontWeight: FontWeight.bold)),
                ],
              ),
              const SizedBox(height: 8),
              ClipRRect(
                borderRadius: BorderRadius.circular(4),
                child: LinearProgressIndicator(value: progress, minHeight: 6, backgroundColor: _D.bgElevated, valueColor: const AlwaysStoppedAnimation<Color>(_D.gold)),
              ),
            ],
          ),
        ),

        // Question
        Expanded(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(q['question_text'] ?? '', style: const TextStyle(color: _D.textPrimary, fontSize: 16, fontWeight: FontWeight.w600)),
                const SizedBox(height: 24),
                if (type == 'scale') _buildScaleQuestion(q),
                if (type == 'multiple_choice') _buildMultipleChoiceQuestion(q),
                if (type == 'multi_select') _buildMultiSelectQuestion(q),
                if (type == 'open_text') _buildOpenTextQuestion(q),
                if (type == 'ranking') _buildMultipleChoiceQuestion(q),
              ],
            ),
          ),
        ),

        // Navigation
        Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              if (_currentIndex > 0)
                OutlinedButton(
                  style: OutlinedButton.styleFrom(side: const BorderSide(color: _D.gold)),
                  onPressed: () => setState(() => _currentIndex--),
                  child: const Text('Back', style: TextStyle(color: _D.gold)),
                ),
              const Spacer(),
              if (_currentIndex < _questions.length - 1)
                ElevatedButton(
                  style: ElevatedButton.styleFrom(backgroundColor: _D.gold),
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

  Widget _buildScaleQuestion(Map<String, dynamic> q) {
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
          activeColor: _D.gold,
          inactiveColor: _D.bgElevated,
          label: current.toInt().toString(),
          onChanged: (v) => setState(() => _answers[_currentIndex] = v),
        ),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(q['scale_min_label'] ?? min.toInt().toString(), style: const TextStyle(color: _D.textSecondary, fontSize: 11)),
            Text(current.toInt().toString(), style: const TextStyle(color: _D.gold, fontSize: 18, fontWeight: FontWeight.bold)),
            Text(q['scale_max_label'] ?? max.toInt().toString(), style: const TextStyle(color: _D.textSecondary, fontSize: 11)),
          ],
        ),
      ],
    );
  }

  Widget _buildMultipleChoiceQuestion(Map<String, dynamic> q) {
    final options = (q['options'] as List?)?.cast<Map<String, dynamic>>() ?? [];
    final selected = _answers[_currentIndex];
    return Column(
      children: options.map((opt) {
        final isSelected = selected == opt['id'] || selected == opt['text'];
        return Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: InkWell(
            borderRadius: BorderRadius.circular(8),
            onTap: () => setState(() => _answers[_currentIndex] = opt['id'] ?? opt['text']),
            child: Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: isSelected ? _D.gold.withOpacity(0.1) : _D.bgElevated,
                border: Border.all(color: isSelected ? _D.gold : Colors.white10),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                children: [
                  Icon(isSelected ? Icons.radio_button_checked : Icons.radio_button_off, color: isSelected ? _D.gold : _D.textSecondary, size: 20),
                  const SizedBox(width: 12),
                  Expanded(child: Text(opt['text'] ?? opt['label'] ?? '', style: TextStyle(color: isSelected ? _D.gold : _D.textPrimary, fontSize: 13))),
                ],
              ),
            ),
          ),
        );
      }).toList(),
    );
  }

  Widget _buildMultiSelectQuestion(Map<String, dynamic> q) {
    final options = (q['options'] as List?)?.cast<Map<String, dynamic>>() ?? [];
    final selected = (_answers[_currentIndex] as List?) ?? [];
    return Column(
      children: options.map((opt) {
        final key = opt['id'] ?? opt['text'];
        final isSelected = selected.contains(key);
        return Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: InkWell(
            borderRadius: BorderRadius.circular(8),
            onTap: () {
              setState(() {
                final list = List.from(selected);
                if (isSelected) { list.remove(key); } else { list.add(key); }
                _answers[_currentIndex] = list;
              });
            },
            child: Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: isSelected ? _D.purple.withOpacity(0.1) : _D.bgElevated,
                border: Border.all(color: isSelected ? _D.purple : Colors.white10),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                children: [
                  Icon(isSelected ? Icons.check_box : Icons.check_box_outline_blank, color: isSelected ? _D.purple : _D.textSecondary, size: 20),
                  const SizedBox(width: 12),
                  Expanded(child: Text(opt['text'] ?? opt['label'] ?? '', style: TextStyle(color: isSelected ? _D.purple : _D.textPrimary, fontSize: 13))),
                ],
              ),
            ),
          ),
        );
      }).toList(),
    );
  }

  Widget _buildOpenTextQuestion(Map<String, dynamic> q) {
    return TextField(
      style: const TextStyle(color: _D.textPrimary, fontSize: 13),
      maxLines: 5,
      decoration: InputDecoration(
        hintText: 'Type your response...',
        hintStyle: TextStyle(color: Colors.grey[600]),
        filled: true,
        fillColor: _D.bgElevated,
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: const BorderSide(color: Colors.white10)),
        enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: const BorderSide(color: Colors.white10)),
        focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: const BorderSide(color: _D.gold)),
      ),
      onChanged: (v) => _answers[_currentIndex] = v,
      controller: TextEditingController(text: _answers[_currentIndex]?.toString() ?? ''),
    );
  }
}
