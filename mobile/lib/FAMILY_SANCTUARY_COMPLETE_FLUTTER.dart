// =============================================================================
// FAMILY SANCTUARY - COMPLETE FLUTTER IMPLEMENTATION
// =============================================================================
// This replaces/enhances the FamilySanctuaryScreen in main.dart
// Implementation Date: January 27, 2026
// =============================================================================

// =============================================================================
// PART 1: STATE VARIABLES
// Add these to _FamilySanctuaryScreenState class (after existing variables)
// =============================================================================

  // === ENTRY QUESTIONS STATE ===
  bool _showEntryQuestions = true;
  int _entryQuestionStep = 0;
  final TextEditingController _entryQ1Controller = TextEditingController(); // What happened?
  final TextEditingController _entryQ2Controller = TextEditingController(); // Your goal?
  final TextEditingController _entryQ3Controller = TextEditingController(); // What other needs to know?
  bool _waitingForOthers = false;
  Map<String, bool> _membersReady = {};
  
  // === PRIVATE COACHING STATE ===
  bool _inPrivateCoaching = false;
  String? _currentCoachingInterventionId;
  List<Map<String, dynamic>> _coachingMessages = [];
  int _coachingAttempt = 0;
  bool _coachingIsDeescalated = false;
  bool _showAssistedResponseOffer = false;
  String? _assistedResponse;
  String? _assistedResponseExplanation;
  final TextEditingController _coachingMessageController = TextEditingController();
  
  // === SANCTUARY PAUSED STATE ===
  bool _sanctuaryPaused = false;
  String _pausedReason = "";
  List<String> _membersInCoaching = [];
  
  // === SESSION GOALS (stored from entry questions) ===
  Map<String, dynamic>? _mySessionGoals;


// =============================================================================
// PART 2: ADD NEW WEBSOCKET MESSAGE HANDLERS
// Add these cases to the switch statement in _handleSanctuaryMessage
// =============================================================================

      // === ENTRY QUESTIONS FLOW ===
      case 'sanctuary_onboarding_required':
        setState(() {
          _showEntryQuestions = true;
          _entryQuestionStep = 0;
        });
        break;
        
      case 'sanctuary_onboarding_complete':
        setState(() {
          _showEntryQuestions = false;
          _waitingForOthers = true;
        });
        _showInfo(data['message'] ?? 'Waiting for other members...');
        break;
        
      case 'sanctuary_member_ready':
        setState(() {
          _membersReady[data['member_id']] = true;
        });
        break;
        
      case 'sanctuary_all_ready':
        setState(() {
          _waitingForOthers = false;
          _showEntryQuestions = false;
        });
        break;
        
      case 'sanctuary_session_started':
        setState(() {
          _waitingForOthers = false;
          _showEntryQuestions = false;
        });
        _addSystemMessage(data['message'] ?? 'Session has begun. 💙');
        break;
      
      // === COACHING FLOW ===
      case 'sanctuary_coaching_started':
        print('>>> SANCTUARY: Entering private coaching');
        setState(() {
          _inPrivateCoaching = true;
          _sanctuaryPaused = false;
          _coachingMessages = [];
          _coachingAttempt = 1;
          _coachingIsDeescalated = false;
          _showAssistedResponseOffer = false;
          _currentCoachingInterventionId = data['intervention_id'];
          
          final coachingMsg = data['coaching_message'];
          if (coachingMsg != null) {
            _coachingMessages.add({
              'role': coachingMsg['role'] ?? 'assistant',
              'content': coachingMsg['content'] ?? '',
              'attempt': coachingMsg['attempt_number'] ?? 1,
            });
          }
        });
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(data['message'] ?? '🔒 Private coaching started'),
            backgroundColor: Colors.blue,
          ),
        );
        break;
        
      case 'sanctuary_coaching_response':
        final coachingMsg = data['coaching_message'];
        setState(() {
          _coachingAttempt = coachingMsg?['attempt_number'] ?? _coachingAttempt;
          _coachingIsDeescalated = data['is_deescalated'] ?? false;
          _showAssistedResponseOffer = data['offer_assisted_response'] ?? false;
          
          if (coachingMsg != null) {
            _coachingMessages.add({
              'role': 'assistant',
              'content': coachingMsg['content'] ?? '',
              'attempt': coachingMsg['attempt_number'],
            });
          }
        });
        
        if (_showAssistedResponseOffer) {
          _showAssistedResponseDialog(data['assisted_response_cost'] ?? 3.00);
        }
        break;
        
      case 'sanctuary_coaching_completed':
        setState(() {
          _inPrivateCoaching = false;
          _coachingMessages = [];
          _coachingAttempt = 0;
          _assistedResponse = data['assisted_response'];
        });
        
        if (_assistedResponse != null && _assistedResponse!.isNotEmpty) {
          _showUseAssistedResponseDialog();
        }
        
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(data['message'] ?? 'Welcome back to the sanctuary'),
            backgroundColor: Colors.green,
          ),
        );
        break;
        
      case 'sanctuary_assisted_response_generated':
        setState(() {
          _assistedResponse = data['assisted_response'];
          _assistedResponseExplanation = data['explanation'];
        });
        _showUseAssistedResponseDialog();
        break;
      
      // === SANCTUARY PAUSED (other member in coaching) ===
      case 'sanctuary_member_coaching':
        setState(() {
          _sanctuaryPaused = true;
          _pausedReason = data['message'] ?? 'A family member is in private coaching.';
          if (!_membersInCoaching.contains(data['member_id'])) {
            _membersInCoaching.add(data['member_id']);
          }
        });
        break;
        
      case 'sanctuary_member_returned':
        setState(() {
          _membersInCoaching.remove(data['member_id']);
        });
        _addSystemMessage(data['message'] ?? 'A family member has returned.');
        break;
        
      case 'sanctuary_resumed':
        setState(() {
          _sanctuaryPaused = false;
          _pausedReason = "";
          _membersInCoaching = [];
        });
        _addSystemMessage(data['message'] ?? 'Sanctuary resumed. 💙');
        break;
      
      // === SESSION COMPLETE ===
      case 'sanctuary_complete':
        _showSessionSummaryDialog(data);
        break;


// =============================================================================
// PART 3: ENTRY QUESTIONS UI
// =============================================================================

  Widget _buildEntryQuestionsUI() {
    final questions = [
      {
        'title': 'Question 1 of 3',
        'question': 'What brings you to this session today?\nWhat happened?',
        'controller': _entryQ1Controller,
        'hint': 'Share what led to this moment...',
      },
      {
        'title': 'Question 2 of 3',
        'question': 'What do YOU hope to achieve in this session?\nWhat\'s your personal goal?',
        'controller': _entryQ2Controller,
        'hint': 'I want to...',
      },
      {
        'title': 'Question 3 of 3',
        'question': 'What do you think the OTHER person needs to understand about how you feel?',
        'controller': _entryQ3Controller,
        'hint': 'I need them to know...',
      },
    ];
    
    final q = questions[_entryQuestionStep];
    
    return Container(
      color: const Color(0xFF0a1628),
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Header
              Row(
                children: [
                  const Icon(Icons.favorite, color: Colors.blue, size: 28),
                  const SizedBox(width: 12),
                  const Text(
                    'Welcome to Family Sanctuary',
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 24),
              
              // Confidential notice
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Colors.blue.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: Colors.blue.withOpacity(0.3)),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.lock, color: Colors.blue, size: 18),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        'Your answers are CONFIDENTIAL\n(not shared with other members)',
                        style: TextStyle(color: Colors.blue[200], fontSize: 12),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 32),
              
              // Progress indicator
              Row(
                children: [
                  for (int i = 0; i < 3; i++) ...[
                    Expanded(
                      child: Container(
                        height: 4,
                        decoration: BoxDecoration(
                          color: i <= _entryQuestionStep 
                              ? Colors.blue 
                              : Colors.grey[700],
                          borderRadius: BorderRadius.circular(2),
                        ),
                      ),
                    ),
                    if (i < 2) const SizedBox(width: 8),
                  ],
                ],
              ),
              const SizedBox(height: 8),
              
              // Question number
              Text(
                q['title'] as String,
                style: TextStyle(color: Colors.grey[500], fontSize: 12),
              ),
              const SizedBox(height: 16),
              
              // Question
              Text(
                q['question'] as String,
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 16,
                  height: 1.4,
                ),
              ),
              const SizedBox(height: 24),
              
              // Answer field
              Expanded(
                child: TextField(
                  controller: q['controller'] as TextEditingController,
                  maxLines: null,
                  expands: true,
                  textAlignVertical: TextAlignVertical.top,
                  style: const TextStyle(color: Colors.white),
                  decoration: InputDecoration(
                    hintText: q['hint'] as String,
                    hintStyle: TextStyle(color: Colors.grey[600]),
                    filled: true,
                    fillColor: Colors.grey[900],
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: BorderSide.none,
                    ),
                    contentPadding: const EdgeInsets.all(16),
                  ),
                ),
              ),
              const SizedBox(height: 24),
              
              // Navigation buttons
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  if (_entryQuestionStep > 0)
                    TextButton.icon(
                      onPressed: () {
                        setState(() => _entryQuestionStep--);
                      },
                      icon: const Icon(Icons.arrow_back),
                      label: const Text('Back'),
                      style: TextButton.styleFrom(foregroundColor: Colors.grey),
                    )
                  else
                    const SizedBox(),
                  
                  ElevatedButton(
                    onPressed: () {
                      final controller = q['controller'] as TextEditingController;
                      if (controller.text.trim().isEmpty) {
                        _showError('Please share your thoughts before continuing.');
                        return;
                      }
                      
                      if (_entryQuestionStep < 2) {
                        setState(() => _entryQuestionStep++);
                      } else {
                        _submitEntryQuestions();
                      }
                    },
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.blue,
                      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
                    ),
                    child: Text(_entryQuestionStep < 2 ? 'Next →' : 'Begin Session →'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
  
  void _submitEntryQuestions() {
    _sanctuaryChannel?.sink.add(jsonEncode({
      'type': 'sanctuary_submit_onboarding',
      'sanctuary_id': _sanctuaryId,
      'responses': {
        'what_happened': _entryQ1Controller.text.trim(),
        'personal_goal': _entryQ2Controller.text.trim(),
        'what_other_needs_to_know': _entryQ3Controller.text.trim(),
      },
    }));
    
    setState(() {
      _mySessionGoals = {
        'what_happened': _entryQ1Controller.text.trim(),
        'personal_goal': _entryQ2Controller.text.trim(),
        'what_other_needs_to_know': _entryQ3Controller.text.trim(),
      };
      _showEntryQuestions = false;
      _waitingForOthers = true;
    });
  }


// =============================================================================
// PART 4: WAITING FOR OTHERS UI
// =============================================================================

  Widget _buildWaitingForOthersUI() {
    return Container(
      color: const Color(0xFF0a1628),
      child: Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.favorite, color: Colors.blue, size: 48),
              const SizedBox(height: 24),
              const Text(
                'Thanks for sharing 💙',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 20,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 12),
              Text(
                'Your goals for this session have been saved.',
                style: TextStyle(color: Colors.grey[400]),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 32),
              
              // Goal reminder
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: Colors.blue.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: Colors.blue.withOpacity(0.3)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        const Icon(Icons.flag, color: Colors.blue, size: 18),
                        const SizedBox(width: 8),
                        const Text(
                          'Your Goal:',
                          style: TextStyle(color: Colors.blue, fontWeight: FontWeight.bold),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Text(
                      _mySessionGoals?['personal_goal'] ?? '',
                      style: const TextStyle(color: Colors.white, fontStyle: FontStyle.italic),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 32),
              
              // Waiting animation
              const CircularProgressIndicator(color: Colors.blue),
              const SizedBox(height: 16),
              Text(
                'Waiting for other family members\nto complete their questions...',
                style: TextStyle(color: Colors.grey[500]),
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      ),
    );
  }


// =============================================================================
// PART 5: PRIVATE COACHING UI
// =============================================================================

  Widget _buildPrivateCoachingUI() {
    return Container(
      color: const Color(0xFF0D1B2A),
      child: Column(
        children: [
          // Header
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: Colors.blue.withOpacity(0.2),
              border: Border(
                bottom: BorderSide(color: Colors.blue.withOpacity(0.3)),
              ),
            ),
            child: Row(
              children: [
                const Icon(Icons.lock, color: Colors.blue, size: 24),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Private Coaching',
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      Text(
                        '🔒 This conversation is confidential',
                        style: TextStyle(color: Colors.blue[200], fontSize: 12),
                      ),
                    ],
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  decoration: BoxDecoration(
                    color: Colors.blue.withOpacity(0.3),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Text(
                    'Step $_coachingAttempt/5',
                    style: const TextStyle(color: Colors.white, fontSize: 12),
                  ),
                ),
              ],
            ),
          ),
          
          // Messages
          Expanded(
            child: ListView.builder(
              padding: const EdgeInsets.all(16),
              itemCount: _coachingMessages.length,
              itemBuilder: (context, index) {
                final msg = _coachingMessages[index];
                final isNate = msg['role'] == 'assistant';
                
                return Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Row(
                    mainAxisAlignment: isNate ? MainAxisAlignment.start : MainAxisAlignment.end,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (isNate) ...[
                        CircleAvatar(
                          radius: 16,
                          backgroundColor: Colors.blue,
                          child: const Icon(Icons.psychology, color: Colors.white, size: 18),
                        ),
                        const SizedBox(width: 8),
                      ],
                      Flexible(
                        child: Container(
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: isNate ? Colors.blue.withOpacity(0.2) : Colors.grey[800],
                            borderRadius: BorderRadius.circular(12),
                            border: isNate ? Border.all(color: Colors.blue.withOpacity(0.3)) : null,
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              if (isNate)
                                Padding(
                                  padding: const EdgeInsets.only(bottom: 4),
                                  child: Text(
                                    '💙 Little Nate',
                                    style: TextStyle(
                                      color: Colors.blue[300],
                                      fontSize: 11,
                                      fontWeight: FontWeight.bold,
                                    ),
                                  ),
                                ),
                              Text(
                                msg['content'] ?? '',
                                style: const TextStyle(color: Colors.white, fontSize: 14),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
                );
              },
            ),
          ),
          
          // De-escalation indicator
          if (_coachingIsDeescalated)
            Container(
              padding: const EdgeInsets.all(12),
              margin: const EdgeInsets.symmetric(horizontal: 16),
              decoration: BoxDecoration(
                color: Colors.green.withOpacity(0.2),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: Colors.green.withOpacity(0.3)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.check_circle, color: Colors.green, size: 20),
                  const SizedBox(width: 8),
                  const Expanded(
                    child: Text(
                      'You seem calmer. Ready to return?',
                      style: TextStyle(color: Colors.green, fontSize: 13),
                    ),
                  ),
                  ElevatedButton(
                    onPressed: () => _completeCoaching(false),
                    style: ElevatedButton.styleFrom(backgroundColor: Colors.green),
                    child: const Text('Return'),
                  ),
                ],
              ),
            ),
          
          // Input area
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: const Color(0xFF0D1B2A),
              border: Border(top: BorderSide(color: Colors.blue.withOpacity(0.2))),
            ),
            child: Column(
              children: [
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _coachingMessageController,
                        style: const TextStyle(color: Colors.white),
                        decoration: InputDecoration(
                          hintText: 'Share with Little Nate (confidential)...',
                          hintStyle: TextStyle(color: Colors.grey[500]),
                          filled: true,
                          fillColor: Colors.grey[900],
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(24),
                            borderSide: BorderSide.none,
                          ),
                          contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                        ),
                        onSubmitted: (_) => _sendCoachingMessage(),
                      ),
                    ),
                    const SizedBox(width: 8),
                    IconButton(
                      onPressed: _sendCoachingMessage,
                      icon: const Icon(Icons.send, color: Colors.blue),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                  children: [
                    TextButton.icon(
                      onPressed: () => _completeCoaching(false),
                      icon: const Icon(Icons.arrow_back, size: 18),
                      label: const Text('Return to Sanctuary'),
                      style: TextButton.styleFrom(foregroundColor: Colors.grey[400]),
                    ),
                    if (_coachingAttempt >= 3)
                      TextButton.icon(
                        onPressed: _requestAssistedResponse,
                        icon: const Icon(Icons.auto_fix_high, size: 18),
                        label: const Text('Get Help (+\$3)'),
                        style: TextButton.styleFrom(foregroundColor: Colors.amber),
                      ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }


// =============================================================================
// PART 6: SANCTUARY PAUSED UI
// =============================================================================

  Widget _buildSanctuaryPausedOverlay() {
    return Container(
      color: Colors.black54,
      child: Center(
        child: Container(
          margin: const EdgeInsets.all(32),
          padding: const EdgeInsets.all(24),
          decoration: BoxDecoration(
            color: const Color(0xFF1a1a2e),
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: Colors.orange.withOpacity(0.3)),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.pause_circle, color: Colors.orange, size: 48),
              const SizedBox(height: 16),
              const Text(
                'Sanctuary Paused',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 12),
              Text(
                _pausedReason,
                style: TextStyle(color: Colors.grey[400]),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 16),
              
              // Who's in coaching
              if (_membersInCoaching.isNotEmpty)
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.blue.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Column(
                    children: [
                      for (final memberId in _membersInCoaching)
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 4),
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              const Icon(Icons.psychology, color: Colors.blue, size: 16),
                              const SizedBox(width: 8),
                              Text(
                                '${_getMemberName(memberId)} is in coaching',
                                style: TextStyle(color: Colors.blue[200], fontSize: 13),
                              ),
                            ],
                          ),
                        ),
                    ],
                  ),
                ),
              const SizedBox(height: 16),
              const CircularProgressIndicator(color: Colors.orange),
              const SizedBox(height: 12),
              Text(
                'Waiting for everyone to return...',
                style: TextStyle(color: Colors.grey[500], fontSize: 12),
              ),
            ],
          ),
        ),
      ),
    );
  }
  
  String _getMemberName(String memberId) {
    final member = _members.firstWhere(
      (m) => m['user_id'] == memberId,
      orElse: () => {'name': 'Family member'},
    );
    return member['name'] ?? 'Family member';
  }


// =============================================================================
// PART 7: COACHING HELPER METHODS
// =============================================================================

  void _sendCoachingMessage() {
    final message = _coachingMessageController.text.trim();
    if (message.isEmpty) return;
    
    setState(() {
      _coachingMessages.add({
        'role': 'user',
        'content': message,
        'attempt': _coachingAttempt,
      });
    });
    
    _sanctuaryChannel?.sink.add(jsonEncode({
      'type': 'sanctuary_coaching_message',
      'sanctuary_id': _sanctuaryId,
      'message': message,
    }));
    
    _coachingMessageController.clear();
  }
  
  void _completeCoaching(bool requestAssisted) {
    _sanctuaryChannel?.sink.add(jsonEncode({
      'type': 'sanctuary_coaching_complete',
      'sanctuary_id': _sanctuaryId,
      'request_assisted_response': requestAssisted,
    }));
  }
  
  void _requestAssistedResponse() {
    _sanctuaryChannel?.sink.add(jsonEncode({
      'type': 'sanctuary_request_assisted_response',
      'sanctuary_id': _sanctuaryId,
    }));
  }
  
  void _showAssistedResponseDialog(double cost) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1a1a2e),
        title: Row(
          children: [
            const Icon(Icons.auto_fix_high, color: Colors.amber),
            const SizedBox(width: 8),
            const Text('Need Help?', style: TextStyle(color: Colors.white)),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'I can help you craft a response that expresses your feelings '
              'in a way your family can hear.',
              style: TextStyle(color: Colors.white70),
            ),
            const SizedBox(height: 12),
            Text('💰 Assisted Response: \$${cost.toStringAsFixed(2)}',
                style: const TextStyle(color: Colors.amber)),
            const SizedBox(height: 8),
            Text('🔒 Your private conversation stays confidential.',
                style: TextStyle(color: Colors.blue[200], fontSize: 12)),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Keep Trying', style: TextStyle(color: Colors.grey)),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(ctx);
              _requestAssistedResponse();
            },
            style: ElevatedButton.styleFrom(backgroundColor: Colors.amber),
            child: Text('Get Help (\$${cost.toStringAsFixed(2)})'),
          ),
        ],
      ),
    );
  }
  
  void _showUseAssistedResponseDialog() {
    final editController = TextEditingController(text: _assistedResponse);
    
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1a1a2e),
        title: Row(
          children: [
            const Icon(Icons.edit_note, color: Colors.green),
            const SizedBox(width: 8),
            const Text('Your Message', style: TextStyle(color: Colors.white)),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (_assistedResponseExplanation != null &&
                _assistedResponseExplanation!.isNotEmpty) ...[
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: Colors.blue.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  '💡 $_assistedResponseExplanation',
                  style: TextStyle(color: Colors.blue[200], fontSize: 12),
                ),
              ),
              const SizedBox(height: 12),
            ],
            const Text('Edit if needed, then send:',
                style: TextStyle(color: Colors.white70, fontSize: 12)),
            const SizedBox(height: 8),
            TextField(
              controller: editController,
              maxLines: 4,
              style: const TextStyle(color: Colors.white),
              decoration: InputDecoration(
                filled: true,
                fillColor: Colors.grey[900],
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel', style: TextStyle(color: Colors.grey)),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(ctx);
              _completeCoaching(false);
              Future.delayed(const Duration(milliseconds: 500), () {
                _sendSanctuaryMessage(editController.text);
              });
            },
            style: ElevatedButton.styleFrom(backgroundColor: Colors.green),
            child: const Text('Send to Sanctuary'),
          ),
        ],
      ),
    );
  }
  
  void _showSessionSummaryDialog(Map<String, dynamic> data) {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1a1a2e),
        title: Row(
          children: [
            const Icon(Icons.favorite, color: Colors.blue),
            const SizedBox(width: 8),
            const Text('Session Complete', style: TextStyle(color: Colors.white)),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Great work today! 💙', style: TextStyle(color: Colors.grey[300])),
            const SizedBox(height: 16),
            Text('Duration: ${data['duration'] ?? 'N/A'}',
                style: const TextStyle(color: Colors.white70)),
            Text('Messages: ${data['message_count'] ?? 0}',
                style: const TextStyle(color: Colors.white70)),
            Text('Total: \$${(data['total_charges'] ?? 0).toStringAsFixed(2)}',
                style: const TextStyle(color: Colors.amber)),
            const SizedBox(height: 16),
            const Text('Did you achieve your goal?',
                style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
            if (_mySessionGoals != null)
              Text('"${_mySessionGoals!['personal_goal']}"',
                  style: TextStyle(color: Colors.blue[200], fontStyle: FontStyle.italic)),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () {
              Navigator.pop(ctx);
              Navigator.pop(context);
            },
            child: const Text('End Session'),
          ),
        ],
      ),
    );
  }


// =============================================================================
// PART 8: UPDATED BUILD METHOD
// Replace the existing build() method body
// =============================================================================

  @override
  Widget build(BuildContext context) {
    // Show entry questions first
    if (_showEntryQuestions) {
      return Scaffold(
        backgroundColor: const Color(0xFF0a1628),
        body: _buildEntryQuestionsUI(),
      );
    }
    
    // Show waiting for others
    if (_waitingForOthers) {
      return Scaffold(
        backgroundColor: const Color(0xFF0a1628),
        body: _buildWaitingForOthersUI(),
      );
    }
    
    // Main sanctuary view
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: const Color(0xFF1a1a2e),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => _showExitConfirmation(),
        ),
        title: Text(_inPrivateCoaching ? '🔒 Private Coaching' : 'Family Sanctuary'),
        actions: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
              decoration: BoxDecoration(
                color: Colors.amber.withOpacity(0.2),
                borderRadius: BorderRadius.circular(16),
              ),
              child: Center(
                child: Text(
                  '\$${_totalCharges.toStringAsFixed(2)}',
                  style: const TextStyle(color: Colors.amber, fontWeight: FontWeight.bold),
                ),
              ),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.more_vert),
            onPressed: () => _showSanctuaryMenu(),
          ),
        ],
      ),
      body: Stack(
        children: [
          // Main content
          _inPrivateCoaching ? _buildPrivateCoachingUI() : _buildNormalSanctuaryUI(),
          
          // Paused overlay
          if (_sanctuaryPaused && !_inPrivateCoaching) _buildSanctuaryPausedOverlay(),
        ],
      ),
    );
  }
  
  Widget _buildNormalSanctuaryUI() {
    return Column(
      children: [
        // Members list
        _buildMembersList(),
        
        // Chat area
        Expanded(child: _buildChatArea()),
        
        // Coaching offer modal
        if (_showCoachingModal && _coachingOffer != null)
          _buildCoachingOfferModal(),
        
        // Input area
        _buildInputArea(),
      ],
    );
  }
