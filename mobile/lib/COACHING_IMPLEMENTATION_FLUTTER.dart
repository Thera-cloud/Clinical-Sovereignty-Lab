// =============================================================================
// PRIVATE COACHING UI IMPLEMENTATION - FLUTTER
// =============================================================================
// Add these to your FamilySanctuaryScreen in main.dart
// Implementation Date: January 27, 2026

// =============================================================================
// PART 1: ADD STATE VARIABLES
// Add these to _FamilySanctuaryScreenState class variables
// =============================================================================

  // Private coaching state
  bool _inPrivateCoaching = false;
  String? _currentCoachingInterventionId;
  List<Map<String, dynamic>> _coachingMessages = [];
  int _coachingAttempt = 0;
  bool _coachingIsDeescalated = false;
  bool _showAssistedResponseOffer = false;
  String? _assistedResponse;
  String? _assistedResponseExplanation;
  bool _sanctuaryPaused = false;
  String _pausedMessage = "";

// =============================================================================
// PART 2: UPDATE _handleSanctuaryMessage TO HANDLE COACHING EVENTS
// Add these cases to the switch/if-else in _handleSanctuaryMessage
// =============================================================================

      // Handle coaching started
      else if (type == 'sanctuary_coaching_started') {
        setState(() {
          _inPrivateCoaching = true;
          _currentCoachingInterventionId = data['intervention_id'];
          _coachingAttempt = 1;
          _coachingMessages = [];
          
          // Add Little Nate's first message
          final coachingMsg = data['coaching_message'];
          if (coachingMsg != null) {
            _coachingMessages.add({
              'role': coachingMsg['role'] ?? 'assistant',
              'content': coachingMsg['content'] ?? '',
              'attempt': coachingMsg['attempt_number'] ?? 1,
            });
          }
        });
        
        // Show notification
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(data['message'] ?? 'Private coaching started'),
            backgroundColor: Colors.blue,
            duration: const Duration(seconds: 3),
          ),
        );
      }
      
      // Handle coaching response from Little Nate
      else if (type == 'sanctuary_coaching_response') {
        final coachingMsg = data['coaching_message'];
        setState(() {
          _coachingAttempt = coachingMsg?['attempt_number'] ?? _coachingAttempt;
          _coachingIsDeescalated = data['is_deescalated'] ?? false;
          _showAssistedResponseOffer = data['offer_assisted_response'] ?? false;
          
          if (coachingMsg != null) {
            _coachingMessages.add({
              'role': coachingMsg['role'] ?? 'assistant',
              'content': coachingMsg['content'] ?? '',
              'attempt': coachingMsg['attempt_number'],
            });
          }
        });
        
        // Show assisted response offer if needed
        if (_showAssistedResponseOffer) {
          _showAssistedResponseDialog(data['assisted_response_cost'] ?? 3.00);
        }
      }
      
      // Handle coaching completed
      else if (type == 'sanctuary_coaching_completed') {
        setState(() {
          _inPrivateCoaching = false;
          _coachingMessages = [];
          _coachingAttempt = 0;
          _showAssistedResponseOffer = false;
          _assistedResponse = data['assisted_response'];
        });
        
        // Show assisted response if generated
        if (_assistedResponse != null && _assistedResponse!.isNotEmpty) {
          _showUseAssistedResponseDialog();
        }
        
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(data['message'] ?? 'Welcome back to the sanctuary'),
            backgroundColor: Colors.green,
          ),
        );
      }
      
      // Handle assisted response generated
      else if (type == 'sanctuary_assisted_response_generated') {
        setState(() {
          _assistedResponse = data['assisted_response'];
          _assistedResponseExplanation = data['explanation'];
        });
        _showUseAssistedResponseDialog();
      }
      
      // Handle other member in coaching (sanctuary paused for us)
      else if (type == 'sanctuary_member_coaching') {
        setState(() {
          _sanctuaryPaused = true;
          _pausedMessage = data['message'] ?? 'A family member is receiving private support.';
        });
      }
      
      // Handle member returned from coaching
      else if (type == 'sanctuary_member_returned') {
        // Just show the message, don't unpause yet
        _addSystemMessage(data['message'] ?? 'A family member has returned.');
      }
      
      // Handle sanctuary resumed
      else if (type == 'sanctuary_resumed') {
        setState(() {
          _sanctuaryPaused = false;
          _pausedMessage = "";
        });
        _addSystemMessage(data['message'] ?? 'The sanctuary has resumed.');
      }


// =============================================================================
// PART 3: ADD COACHING UI WIDGET
// Add this method to build the private coaching interface
// =============================================================================

  Widget _buildPrivateCoachingUI() {
    return Container(
      color: const Color(0xFF0D1B2A), // Darker blue for private space
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
                const Icon(Icons.shield, color: Colors.blue, size: 24),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Private Coaching with Little Nate',
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      Text(
                        '🔒 This conversation is confidential',
                        style: TextStyle(
                          color: Colors.blue[200],
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                ),
                // Attempt counter
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
                    mainAxisAlignment: isNate 
                        ? MainAxisAlignment.start 
                        : MainAxisAlignment.end,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (isNate) ...[
                        CircleAvatar(
                          radius: 16,
                          backgroundColor: Colors.blue,
                          child: const Icon(Icons.psychology, 
                              color: Colors.white, size: 18),
                        ),
                        const SizedBox(width: 8),
                      ],
                      Flexible(
                        child: Container(
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: isNate 
                                ? Colors.blue.withOpacity(0.2)
                                : Colors.grey[800],
                            borderRadius: BorderRadius.circular(12),
                            border: isNate 
                                ? Border.all(color: Colors.blue.withOpacity(0.3))
                                : null,
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              if (isNate)
                                Padding(
                                  padding: const EdgeInsets.only(bottom: 4),
                                  child: Text(
                                    'Little Nate',
                                    style: TextStyle(
                                      color: Colors.blue[300],
                                      fontSize: 11,
                                      fontWeight: FontWeight.bold,
                                    ),
                                  ),
                                ),
                              Text(
                                msg['content'] ?? '',
                                style: const TextStyle(
                                  color: Colors.white,
                                  fontSize: 14,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                      if (!isNate) const SizedBox(width: 8),
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
                      'You seem calmer. Ready to return to your family?',
                      style: TextStyle(color: Colors.green, fontSize: 13),
                    ),
                  ),
                  TextButton(
                    onPressed: _completeCoaching,
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
              border: Border(
                top: BorderSide(color: Colors.blue.withOpacity(0.2)),
              ),
            ),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _messageController,
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
                      contentPadding: const EdgeInsets.symmetric(
                        horizontal: 16, vertical: 12),
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
          ),
          
          // Action buttons
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceEvenly,
              children: [
                TextButton.icon(
                  onPressed: _completeCoaching,
                  icon: const Icon(Icons.arrow_back, size: 18),
                  label: const Text('Return to Sanctuary'),
                  style: TextButton.styleFrom(
                    foregroundColor: Colors.grey[400],
                  ),
                ),
                if (_coachingAttempt >= 3)
                  TextButton.icon(
                    onPressed: () => _requestAssistedResponse(),
                    icon: const Icon(Icons.auto_fix_high, size: 18),
                    label: const Text('Get Help Writing (+\$3)'),
                    style: TextButton.styleFrom(
                      foregroundColor: Colors.amber,
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }


// =============================================================================
// PART 4: ADD COACHING METHODS
// =============================================================================

  void _sendCoachingMessage() {
    final message = _messageController.text.trim();
    if (message.isEmpty) return;
    
    // Add to local messages immediately
    setState(() {
      _coachingMessages.add({
        'role': 'user',
        'content': message,
        'attempt': _coachingAttempt,
      });
    });
    
    // Send to server
    _sanctuaryChannel?.sink.add(jsonEncode({
      'type': 'sanctuary_coaching_message',
      'sanctuary_id': _sanctuaryId,
      'message': message,
    }));
    
    _messageController.clear();
  }
  
  void _completeCoaching({bool requestAssisted = false}) {
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
            Text(
              '💰 Assisted Response: \$${cost.toStringAsFixed(2)}',
              style: const TextStyle(color: Colors.amber),
            ),
            const SizedBox(height: 8),
            Text(
              '🔒 Your private conversation stays confidential.',
              style: TextStyle(color: Colors.blue[200], fontSize: 12),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Keep Trying', 
                style: TextStyle(color: Colors.grey)),
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
    final TextEditingController editController = 
        TextEditingController(text: _assistedResponse);
    
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
                  '💡 ${_assistedResponseExplanation}',
                  style: TextStyle(color: Colors.blue[200], fontSize: 12),
                ),
              ),
              const SizedBox(height: 12),
            ],
            const Text(
              'Edit if needed, then send:',
              style: TextStyle(color: Colors.white70, fontSize: 12),
            ),
            const SizedBox(height: 8),
            TextField(
              controller: editController,
              maxLines: 4,
              style: const TextStyle(color: Colors.white),
              decoration: InputDecoration(
                filled: true,
                fillColor: Colors.grey[900],
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                ),
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
              // Complete coaching and send the message
              _completeCoaching();
              // Then send the assisted response to sanctuary
              Future.delayed(const Duration(milliseconds: 500), () {
                _sendMessage(editController.text);
              });
            },
            style: ElevatedButton.styleFrom(backgroundColor: Colors.green),
            child: const Text('Send to Sanctuary'),
          ),
        ],
      ),
    );
  }


// =============================================================================
// PART 5: UPDATE BUILD METHOD
// Modify the build method to show coaching UI when in private coaching
// =============================================================================

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: const Color(0xFF1a1a2e),
        title: Text(_inPrivateCoaching 
            ? 'Private Coaching' 
            : 'Family Sanctuary'),
        actions: [
          // Show billing total
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
                  style: const TextStyle(
                    color: Colors.amber,
                    fontWeight: FontWeight.bold,
                  ),
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
      body: _inPrivateCoaching 
          ? _buildPrivateCoachingUI()
          : _buildSanctuaryUI(),
    );
  }
  
  Widget _buildSanctuaryUI() {
    return Column(
      children: [
        // Paused banner (when other member is in coaching)
        if (_sanctuaryPaused)
          Container(
            padding: const EdgeInsets.all(12),
            color: Colors.orange.withOpacity(0.2),
            child: Row(
              children: [
                const Icon(Icons.pause_circle, color: Colors.orange, size: 20),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    _pausedMessage,
                    style: const TextStyle(color: Colors.orange, fontSize: 13),
                  ),
                ),
              ],
            ),
          ),
        
        // Member list
        _buildMembersList(),
        
        // Chat area
        Expanded(child: _buildChatArea()),
        
        // Input area
        _buildInputArea(),
      ],
    );
  }


// =============================================================================
// PART 6: UPDATE COACHING OFFER DIALOG
// Replace the existing coaching offer dialog to match new flow
// =============================================================================

  void _showCoachingOfferDialog(Map<String, dynamic> data) {
    final cost = data['coaching_cost'] ?? 5.00;
    final assistedCost = data['assisted_response_cost'] ?? 3.00;
    final isFree = data['is_first_coaching'] ?? false;
    final interventionId = data['intervention_id'];
    
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1a1a2e),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: Row(
          children: [
            const Icon(Icons.favorite, color: Colors.blue, size: 28),
            const SizedBox(width: 12),
            const Text('Coaching Offered', 
                style: TextStyle(color: Colors.white)),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              data['message'] ?? 'I notice an opportunity to provide support. '
                  'Would you like coaching on this moment?',
              style: const TextStyle(color: Colors.white70),
            ),
            const SizedBox(height: 16),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.blue.withOpacity(0.1),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: Colors.blue.withOpacity(0.3)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(
                        isFree ? Icons.card_giftcard : Icons.paid,
                        color: isFree ? Colors.green : Colors.amber,
                        size: 20,
                      ),
                      const SizedBox(width: 8),
                      Text(
                        isFree 
                            ? '🎁 First coaching is FREE!'
                            : 'Coaching: \$${cost.toStringAsFixed(2)}',
                        style: TextStyle(
                          color: isFree ? Colors.green : Colors.amber,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    '• Private 1-on-1 with Little Nate\n'
                    '• De-escalation support\n'
                    '• Optional: Assisted response (+\$${assistedCost.toStringAsFixed(2)})',
                    style: TextStyle(color: Colors.grey[400], fontSize: 12),
                  ),
                ],
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () {
              Navigator.pop(ctx);
              // Decline coaching
              _sanctuaryChannel?.sink.add(jsonEncode({
                'type': 'sanctuary_coaching_decline',
                'sanctuary_id': _sanctuaryId,
                'intervention_id': interventionId,
              }));
            },
            child: const Text('No Thanks', 
                style: TextStyle(color: Colors.grey)),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(ctx);
              // Accept coaching
              _sanctuaryChannel?.sink.add(jsonEncode({
                'type': 'sanctuary_coaching_accept',
                'sanctuary_id': _sanctuaryId,
                'intervention_id': interventionId,
                'assisted_response': false,
              }));
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.blue,
            ),
            child: Text(isFree ? 'Get Free Coaching' : 'Get Coaching (\$${cost.toStringAsFixed(2)})'),
          ),
        ],
      ),
    );
  }
