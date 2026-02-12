// =============================================================================
// FLUTTER - Update _handleWebSocketMessage in FamilySanctuaryScreen
// Replace the existing switch statement with this updated version
// =============================================================================

void _handleWebSocketMessage(Map<String, dynamic> data) {
  final type = data['type'];
  print('>>> SANCTUARY RECEIVED: $data');
  
  switch (type) {
    // =========================================================================
    // LOGIN RESPONSE (for authentication)
    // =========================================================================
    case 'login_success':
      print('>>> SANCTUARY: Authenticated successfully');
      break;
      
    // =========================================================================
    // SANCTUARY CREATION
    // =========================================================================
    case 'sanctuary_created':
      setState(() {
        _sanctuaryId = data['sanctuary_id'];
        _sanctuaryStatus = data['status'] ?? 'WAITING_FOR_MEMBERS';
        _totalCharges = (data['base_fee_charged'] ?? 20.0).toDouble();
      });
      _showSuccess('Family Sanctuary created!');
      break;
      
    // =========================================================================
    // JOINING (new member)
    // =========================================================================
    case 'sanctuary_joined':
      setState(() {
        _sanctuaryId = data['sanctuary_id'];
        _sanctuaryStatus = data['status'] ?? 'ACTIVE';
        _members = _parseMembersList(data['members']);
      });
      _showSuccess('Joined Family Sanctuary!');
      break;
      
    // =========================================================================
    // RECONNECTION (returning after disconnect/refresh)
    // =========================================================================
    case 'sanctuary_reconnected':
      setState(() {
        _sanctuaryId = data['sanctuary_id'];
        _sanctuaryStatus = data['status'] ?? 'ACTIVE';
        _members = _parseMembersList(data['members']);
      });
      _addSystemMessage(data['message'] ?? 'Reconnected to sanctuary');
      break;
      
    // =========================================================================
    // REJOINING (returning after exit)
    // =========================================================================
    case 'sanctuary_rejoined':
      setState(() {
        _sanctuaryId = data['sanctuary_id'];
        _sanctuaryStatus = data['status'] ?? 'ACTIVE';
        _members = _parseMembersList(data['members']);
      });
      _addSystemMessage(data['message'] ?? 'Welcome back!');
      _showSuccess('Welcome back to the sanctuary!');
      break;
      
    // =========================================================================
    // ONBOARDING (Little Nate greeting)
    // =========================================================================
    case 'sanctuary_onboarding':
      _showOnboardingDialog(data['message']);
      break;
      
    // =========================================================================
    // MEMBER EVENTS
    // =========================================================================
    case 'sanctuary_member_joined':
      final member = data['member'] as Map<String, dynamic>;
      // Only add if not already in list (by id)
      final memberId = member['id'] ?? member['user_id'];
      if (!_members.any((m) => (m['id'] ?? m['user_id']) == memberId)) {
        setState(() => _members.add(member));
      }
      _addSystemMessage('${member['name']} joined');
      break;
      
    case 'sanctuary_member_returned':
      final member = data['member'] as Map<String, dynamic>;
      _addSystemMessage('${member['name']} has returned to the sanctuary');
      break;
      
    case 'sanctuary_member_exited':
      _addSystemMessage(data['message'] ?? 'A member has left');
      break;
      
    // =========================================================================
    // SESSION START (all members ready)
    // =========================================================================
    case 'sanctuary_started':
      setState(() {
        _sanctuaryStatus = 'ACTIVE';
        _members = _parseMembersList(data['members']);
      });
      _addLittleNateMessage(data['opening_message']);
      break;
      
    // =========================================================================
    // MESSAGES
    // =========================================================================
    case 'sanctuary_message':
      _addMessage(data);
      break;
      
    // =========================================================================
    // COACHING
    // =========================================================================
    case 'sanctuary_coaching_offer':
      setState(() {
        _coachingOffer = data;
        _showCoachingModal = true;
      });
      break;
      
    case 'sanctuary_coaching':
      _showCoachingDialog(data);
      break;
      
    case 'sanctuary_coaching_notification':
      _showInfo(data['message']);
      break;
      
    // =========================================================================
    // EXIT FLOW
    // =========================================================================
    case 'sanctuary_exit_checkin':
      _showExitCheckinDialog(data['message']);
      break;
      
    case 'sanctuary_exited':
      _showInfo('You have exited the sanctuary. You can rejoin anytime.');
      Navigator.pop(context);
      break;
      
    // =========================================================================
    // BILLING
    // =========================================================================
    case 'sanctuary_threshold_notification':
      _showBillingThresholdDialog(data);
      break;
      
    // =========================================================================
    // COMPLETION
    // =========================================================================
    case 'sanctuary_completed':
      _showCompletionDialog(data);
      break;
      
    // =========================================================================
    // ERRORS
    // =========================================================================
    case 'error':
      _showError(data['message'] ?? 'An error occurred');
      break;
      
    default:
      print('>>> SANCTUARY: Unhandled message type: $type');
  }
}

// =============================================================================
// HELPER METHOD - Parse members list (handles different formats)
// =============================================================================

List<Map<String, dynamic>> _parseMembersList(dynamic members) {
  if (members == null) return [];
  
  if (members is List) {
    return members.map((m) {
      if (m is String) {
        // Just a name string
        return {'name': m, 'status': 'ACTIVE'};
      } else if (m is Map) {
        // Full member object
        return Map<String, dynamic>.from(m);
      }
      return {'name': m.toString(), 'status': 'ACTIVE'};
    }).toList().cast<Map<String, dynamic>>();
  }
  
  return [];
}

// =============================================================================
// HELPER METHODS - Messages
// =============================================================================

void _addSystemMessage(String text) {
  setState(() {
    _messages.add({
      'type': 'SYSTEM',
      'content': text,
      'timestamp': DateTime.now().toIso8601String(),
    });
  });
  _scrollToBottom();
}

void _addLittleNateMessage(String text) {
  setState(() {
    _messages.add({
      'type': 'LITTLE_NATE',
      'sender_name': 'Little Nate',
      'content': text,
      'timestamp': DateTime.now().toIso8601String(),
    });
  });
  _scrollToBottom();
}

void _addMessage(Map<String, dynamic> data) {
  setState(() {
    _messages.add({
      'type': data['message_type'] ?? 'MEMBER_MESSAGE',
      'sender_id': data['sender_id'],
      'sender_name': data['sender_name'],
      'content': data['content'],
      'timestamp': data['timestamp'] ?? DateTime.now().toIso8601String(),
    });
  });
  _scrollToBottom();
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

// =============================================================================
// HELPER METHODS - Dialogs
// =============================================================================

void _showSuccess(String message) {
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      content: Text(message),
      backgroundColor: Colors.green,
      duration: const Duration(seconds: 2),
    ),
  );
}

void _showError(String message) {
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      content: Text(message),
      backgroundColor: Colors.red,
      duration: const Duration(seconds: 3),
    ),
  );
}

void _showInfo(String message) {
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      content: Text(message),
      backgroundColor: Colors.blue,
      duration: const Duration(seconds: 2),
    ),
  );
}
