/// LITTLE NATE — DOJO Mentor Overlay
/// Floating, draggable overlay for live Zoom coaching sessions.
/// Coach receives real-time mentor observations from Nate across active DOJO lenses.

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../services/dojo_mentor_service.dart';

// =============================================================================
// DESIGN SYSTEM
// =============================================================================

const _kBgVoid = Color(0xFF050505);
const _kGold = Color(0xFFC9A962);
const _kCyan = Color(0xFF4ECDC4);
const _kPurple = Color(0xFF9D4EDD);
const _kTextPrimary = Color(0xFFFFFFFF);
const _kTextSecondary = Color(0xFF888888);
const _kChamber = Color(0xFF0A0A0A);

// =============================================================================
// WIDGET
// =============================================================================

/// Floating overlay for DOJO Mentor during Zoom sessions.
/// Draggable, resizable, shows DOJO chips, coaching cards, quick actions, and input.
class DojoMentorOverlay extends StatefulWidget {
  final Map<String, dynamic> profile;
  final String sessionId;
  final List<String> activeDojos;
  final String? clientId;
  final String sessionMode;
  final WebSocketChannel? socket;
  /// Called when user closes the overlay; parent should remove it from the tree.
  final VoidCallback? onClose;

  const DojoMentorOverlay({
    super.key,
    required this.profile,
    required this.sessionId,
    required this.activeDojos,
    this.clientId,
    this.sessionMode = 'coach_client',
    this.socket,
    this.onClose,
  });

  @override
  State<DojoMentorOverlay> createState() => _DojoMentorOverlayState();
}

class _DojoMentorOverlayState extends State<DojoMentorOverlay> {
  late DojoMentorService _service;
  Offset _position = const Offset(24, 80);
  Size _size = const Size(320, 420);
  final _questionController = TextEditingController();
  Timer? _durationTimer;
  Duration _elapsed = Duration.zero;
  bool _sessionStarted = false;

  @override
  void initState() {
    super.initState();
    _service = DojoMentorService();
    _service.addListener(_onServiceUpdate);

    if (widget.socket != null) {
      _service.setChannel(widget.socket);
      _startSession();
    }
  }

  void _startSession() {
    if (_sessionStarted) return;
    final available = DojoMentorService.availableDojosFromProfile(widget.profile);
    final initial = widget.activeDojos
        .where((d) => available.contains(d))
        .toList();
    if (initial.isEmpty) initial.add('therapist');

    _service.startSession(
      sessionId: widget.sessionId,
      activeDojos: initial,
      clientId: widget.clientId,
      sessionMode: widget.sessionMode,
      coachUserId: widget.profile['hardware_id']?.toString(),
    );
    _sessionStarted = true;
    _durationTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() => _elapsed += const Duration(seconds: 1));
    });
  }

  void _onServiceUpdate() {
    if (mounted) setState(() {});
  }

  @override
  void didUpdateWidget(covariant DojoMentorOverlay oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.socket != oldWidget.socket) {
      _service.setChannel(widget.socket);
      if (widget.socket != null && !_sessionStarted) _startSession();
    }
  }

  @override
  void dispose() {
    _durationTimer?.cancel();
    _service.removeListener(_onServiceUpdate);
    _service.dispose();
    _questionController.dispose();
    super.dispose();
  }

  String _formatDuration(Duration d) {
    final m = d.inMinutes;
    final s = d.inSeconds % 60;
    return '${m.toString().padLeft(2, '0')}:${s.toString().padLeft(2, '0')}';
  }

  void _quickAsk(String prompt) {
    _service.askQuestion(prompt);
  }

  @override
  Widget build(BuildContext context) {
    if (_service.isMinimized) {
      return _buildMinimized();
    }
    return _buildExpanded();
  }

  Widget _buildMinimized() {
    return Positioned(
      left: _position.dx,
      top: _position.dy,
      child: GestureDetector(
        onTap: () => _service.isMinimized = false,
        onPanUpdate: (d) {
          setState(() {
            _position += Offset(d.delta.dx, d.delta.dy);
          });
        },
        child: Container(
          width: 48,
          height: 48,
          decoration: BoxDecoration(
            color: _kBgVoid,
            borderRadius: BorderRadius.circular(24),
            border: Border.all(color: _kGold, width: 2),
            boxShadow: [
              BoxShadow(
                color: _kGold.withOpacity(0.3),
                blurRadius: 8,
                spreadRadius: 0,
              ),
            ],
          ),
          child: const Icon(Icons.school, color: _kGold, size: 26),
        ),
      ),
    );
  }

  Widget _buildExpanded() {
    return Positioned(
      left: _position.dx,
      top: _position.dy,
      child: GestureDetector(
        onPanUpdate: (d) {
          setState(() {
            _position += Offset(d.delta.dx, d.delta.dy);
          });
        },
        child: Material(
          color: Colors.transparent,
          child: Container(
            width: _size.width,
            height: _size.height,
            decoration: BoxDecoration(
              color: _kBgVoid,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: _kGold.withOpacity(0.6), width: 1.5),
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withOpacity(0.5),
                  blurRadius: 16,
                  spreadRadius: 0,
                ),
              ],
            ),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _buildHeader(),
                  _buildDojoChips(),
                  Expanded(child: _buildCoachingFeed()),
                  _buildQuickActions(),
                  _buildInput(),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildHeader() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      color: _kChamber,
      child: Row(
        children: [
          const Icon(Icons.school, color: _kGold, size: 20),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'DOJO Mentor',
                  style: const TextStyle(
                    color: _kGold,
                    fontSize: 14,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                Text(
                  '${_formatDuration(_elapsed)} • ${_modeLabel(widget.sessionMode)}',
                  style: const TextStyle(
                    color: _kTextSecondary,
                    fontSize: 11,
                  ),
                ),
              ],
            ),
          ),
          IconButton(
            icon: const Icon(Icons.minimize, color: _kTextSecondary),
            onPressed: () => _service.isMinimized = true,
            padding: EdgeInsets.zero,
            constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
          ),
          IconButton(
            icon: const Icon(Icons.close, color: _kTextSecondary),
            onPressed: () {
              _service.endSession();
              widget.onClose?.call();
              if (context.mounted && widget.onClose == null) {
                Navigator.of(context).pop();
              }
            },
            padding: EdgeInsets.zero,
            constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
          ),
        ],
      ),
    );
  }

  String _modeLabel(String mode) {
    const labels = {
      'coach_client': 'Client',
      'coach_students': 'Students',
      'judge_debate': 'Debate',
      'lawyer_client': 'Legal',
    };
    return labels[mode] ?? mode;
  }

  Widget _buildDojoChips() {
    final available = DojoMentorService.availableDojosFromProfile(widget.profile);
    if (available.isEmpty) return const SizedBox.shrink();

    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
      child: Row(
        children: available.map((key) {
          final active = _service.activeDojos.contains(key);
          final label = kDojoLabels[key] ?? key;
          return Padding(
            padding: const EdgeInsets.only(right: 6),
            child: FilterChip(
              label: Text(
                label,
                style: TextStyle(
                  fontSize: 11,
                  color: active ? _kBgVoid : _kTextSecondary,
                ),
              ),
              selected: active,
              onSelected: (s) => _service.toggleDojo(key, s),
              backgroundColor: _kChamber,
              selectedColor: _kGold.withOpacity(0.9),
              checkmarkColor: _kBgVoid,
              side: BorderSide(
                color: active ? _kGold : _kTextSecondary.withOpacity(0.4),
              ),
            ),
          );
        }).toList(),
      ),
    );
  }

  Widget _buildCoachingFeed() {
    final cards = _service.coachingCards;
    if (cards.isEmpty) {
      return Center(
        child: Text(
          'Nate will appear here as the session unfolds…',
          style: TextStyle(
            color: _kTextSecondary.withOpacity(0.7),
            fontSize: 13,
            fontStyle: FontStyle.italic,
          ),
        ),
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      itemCount: cards.length,
      itemBuilder: (_, i) {
        final c = cards[i];
        return _CoachingCardTile(card: c);
      },
    );
  }

  Widget _buildQuickActions() {
    return Wrap(
      spacing: 6,
      runSpacing: 6,
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
      children: [
        _QuickActionBtn(
          label: 'What should I ask?',
          onTap: () => _quickAsk('What should I ask the client next?'),
        ),
        _QuickActionBtn(
          label: 'Risk assessment',
          onTap: () => _quickAsk('Risk assessment for this moment in the session'),
        ),
        _QuickActionBtn(
          label: 'Client pattern alert',
          onTap: () => _quickAsk('Alert me to any client patterns I should notice'),
        ),
        _QuickActionBtn(
          label: 'Summarize so far',
          onTap: () => _quickAsk('Summarize the session so far'),
        ),
      ],
    );
  }

  Widget _buildInput() {
    return Container(
      padding: const EdgeInsets.all(8),
      color: _kChamber,
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _questionController,
              decoration: InputDecoration(
                hintText: 'Ask Nate…',
                hintStyle: TextStyle(color: _kTextSecondary.withOpacity(0.6)),
                filled: true,
                fillColor: _kBgVoid,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                  borderSide: BorderSide(color: _kGold.withOpacity(0.4)),
                ),
                contentPadding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 10,
                ),
              ),
              style: const TextStyle(color: _kTextPrimary, fontSize: 13),
              maxLines: 2,
              onSubmitted: (s) {
                if (s.trim().isNotEmpty) {
                  _service.askQuestion(s);
                  _questionController.clear();
                }
              },
            ),
          ),
          const SizedBox(width: 8),
          IconButton(
            onPressed: () {
              final t = _questionController.text.trim();
              if (t.isNotEmpty) {
                _service.askQuestion(t);
                _questionController.clear();
              }
            },
            icon: const Icon(Icons.send, color: _kCyan),
          ),
        ],
      ),
    );
  }
}

// =============================================================================
// SUB-WIDGETS
// =============================================================================

class _CoachingCardTile extends StatelessWidget {
  final CoachingCard card;

  const _CoachingCardTile({required this.card});

  @override
  Widget build(BuildContext context) {
    Color accent = _kCyan;
    IconData icon = Icons.lightbulb_outline;
    if (card.type == 'alert') {
      accent = Colors.orange;
      icon = Icons.warning_amber;
    } else if (card.type == 'answer') {
      accent = _kPurple;
      icon = Icons.chat_bubble_outline;
    } else if (card.type == 'suggestion') {
      accent = _kGold;
      icon = Icons.tips_and_updates;
    }

    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: _kChamber,
          borderRadius: BorderRadius.circular(8),
          border: Border(
            left: BorderSide(color: accent, width: 4),
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, color: accent, size: 14),
                const SizedBox(width: 6),
                Text(
                  _typeLabel(card.type),
                  style: TextStyle(
                    color: accent,
                    fontSize: 10,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                if (card.dojoLens != null) ...[
                  const SizedBox(width: 8),
                  Text(
                    kDojoLabels[card.dojoLens!] ?? card.dojoLens!,
                    style: TextStyle(
                      color: _kTextSecondary.withOpacity(0.8),
                      fontSize: 9,
                    ),
                  ),
                ],
              ],
            ),
            const SizedBox(height: 6),
            Text(
              card.content,
              style: const TextStyle(
                color: _kTextPrimary,
                fontSize: 13,
                height: 1.35,
              ),
            ),
          ],
        ),
      ),
    );
  }

  String _typeLabel(String type) {
    const labels = {
      'observation': 'OBSERVATION',
      'suggestion': 'SUGGESTION',
      'answer': 'ANSWER',
      'alert': 'ALERT',
    };
    return labels[type] ?? type.toUpperCase();
  }
}

class _QuickActionBtn extends StatelessWidget {
  final String label;
  final VoidCallback onTap;

  const _QuickActionBtn({required this.label, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(6),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(
          color: _kChamber,
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: _kGold.withOpacity(0.5)),
        ),
        child: Text(
          label,
          style: const TextStyle(
            color: _kGold,
            fontSize: 11,
          ),
        ),
      ),
    );
  }
}
