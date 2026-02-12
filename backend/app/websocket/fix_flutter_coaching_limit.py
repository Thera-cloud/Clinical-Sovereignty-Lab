#!/usr/bin/env python3
"""
Flutter Fix: Handle Coaching Limit and Extension
=================================================
Adds handlers for:
1. sanctuary_coaching_limit_reached - Shows dialog with continue/return options
2. sanctuary_coaching_extended - Confirms extension, updates step counter
3. sanctuary_assisted_response_generated - Shows the assisted response

Also updates the coaching UI to disable input when limit reached.

Run from anywhere (uses absolute path to main.dart)
"""

import os
import shutil
from datetime import datetime

FILE_PATH = os.path.expanduser("~/Desktop/Clinical-Sovereignty-Lab-2/mobile/lib/main.dart")

def apply_fixes():
    print("=" * 60)
    print("Flutter Fix: Coaching Limit UI")
    print("=" * 60)
    
    if not os.path.exists(FILE_PATH):
        print(f"❌ File not found: {FILE_PATH}")
        return False
    
    # Backup
    backup_path = FILE_PATH + f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy(FILE_PATH, backup_path)
    print(f"📦 Backup: {backup_path}")
    
    with open(FILE_PATH, 'r') as f:
        content = f.read()
    
    fixes_applied = []
    
    # =========================================================================
    # FIX 1: Add state variable for coaching limit
    # =========================================================================
    if "_coachingLimitReached" not in content:
        old_state = "  bool _inPrivateCoaching = false;"
        new_state = """  bool _inPrivateCoaching = false;
  bool _coachingLimitReached = false;
  int _coachingMaxSteps = 5;"""
        
        if old_state in content:
            content = content.replace(old_state, new_state)
            fixes_applied.append("1. Added _coachingLimitReached state variable")
        else:
            print("   ⚠️  Could not find state variable location")
    
    # =========================================================================
    # FIX 2: Add handler for sanctuary_coaching_limit_reached
    # =========================================================================
    if "sanctuary_coaching_limit_reached" not in content:
        insert_marker = """      // COACHING COMPLETED - Return to sanctuary
      case 'sanctuary_coaching_completed':"""
        
        new_handler = """      // COACHING LIMIT REACHED - Offer continuation or return
      case 'sanctuary_coaching_limit_reached':
        print('>>> SANCTUARY: Coaching limit reached');
        setState(() {
          _coachingLimitReached = true;
          _coachingMaxSteps = data['max_steps'] ?? 5;
        });
        _showCoachingLimitDialog(data);
        break;
      
      // COACHING EXTENDED - Session extended after $5 payment
      case 'sanctuary_coaching_extended':
        print('>>> SANCTUARY: Coaching extended');
        setState(() {
          _coachingLimitReached = false;
          _coachingMaxSteps = data['new_max_steps'] ?? 10;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(data['message'] ?? 'Coaching extended!'), backgroundColor: Colors.green),
        );
        break;
      
      // ASSISTED RESPONSE GENERATED
      case 'sanctuary_assisted_response_generated':
        print('>>> SANCTUARY: Assisted response received');
        final assistedResponse = data['assisted_response'] ?? data['response'] ?? '';
        if (assistedResponse.isNotEmpty) {
          setState(() {
            _coachingMessages.add({
              'role': 'assisted',
              'content': '✨ SUGGESTED RESPONSE:\\n\\n$assistedResponse',
              'is_assisted': true,
            });
          });
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Assisted response ready!'), backgroundColor: Colors.green),
          );
        }
        break;
      
      // COACHING COMPLETED - Return to sanctuary
      case 'sanctuary_coaching_completed':"""
        
        if insert_marker in content:
            content = content.replace(insert_marker, new_handler)
            fixes_applied.append("2. Added coaching limit/extended/assisted handlers")
        else:
            print("   ⚠️  Could not find insertion point for limit handler")
    
    # =========================================================================
    # FIX 3: Add the dialog method for coaching limit
    # =========================================================================
    if "_showCoachingLimitDialog" not in content:
        insert_marker = "  void _showError(String message) {"
        
        dialog_method = """  void _showCoachingLimitDialog(Map<String, dynamic> data) {
    final isDeescalated = data['is_deescalated'] ?? false;
    final continueCost = data['options']?['continue_cost'] ?? 5.00;
    final assistedCost = data['options']?['assisted_response_cost'] ?? 3.00;
    
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        backgroundColor: const Color(0xFF1a1a2e),
        title: Row(
          children: [
            Icon(isDeescalated ? Icons.check_circle : Icons.info, color: Colors.blue),
            const SizedBox(width: 8),
            Text(
              isDeescalated ? 'Great Progress!' : 'Coaching Checkpoint',
              style: const TextStyle(color: Colors.white),
            ),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              data['message'] ?? "You've completed your coaching exchanges.",
              style: const TextStyle(color: Colors.white70),
            ),
            const SizedBox(height: 16),
            const Text(
              'What would you like to do?',
              style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold),
            ),
          ],
        ),
        actions: [
          // Return without assisted response
          TextButton(
            onPressed: () {
              Navigator.pop(context);
              _completeCoaching();
            },
            child: const Text('Return to Family', style: TextStyle(color: Colors.grey)),
          ),
          // Get assisted response ($3)
          ElevatedButton(
            onPressed: () {
              Navigator.pop(context);
              _requestAssistedResponse();
              // After a brief delay, complete coaching
              Future.delayed(const Duration(seconds: 2), () {
                _completeCoaching();
              });
            },
            style: ElevatedButton.styleFrom(backgroundColor: Colors.amber[700]),
            child: Text('Get Help + Return (\\$${assistedCost.toStringAsFixed(0)})'),
          ),
          // Continue coaching ($5)
          ElevatedButton(
            onPressed: () {
              Navigator.pop(context);
              _extendCoaching();
            },
            style: ElevatedButton.styleFrom(backgroundColor: Colors.blue),
            child: Text('Continue Coaching (\\$${continueCost.toStringAsFixed(0)})'),
          ),
        ],
      ),
    );
  }
  
  void _extendCoaching() {
    _channel?.sink.add(jsonEncode({
      'type': 'sanctuary_coaching_extend',
      'sanctuary_id': _sanctuaryId,
    }));
    setState(() {
      _coachingLimitReached = false;
    });
  }

  """
        
        if insert_marker in content:
            content = content.replace(insert_marker, dialog_method + insert_marker)
            fixes_applied.append("3. Added _showCoachingLimitDialog method")
        else:
            print("   ⚠️  Could not find insertion point for dialog method")
    
    # =========================================================================
    # FIX 4: Update step counter to show current/max
    # =========================================================================
    old_step_counter = "Text('Step \\$_coachingAttempt/5'"
    new_step_counter = "Text('Step \\$_coachingAttempt/\\$_coachingMaxSteps'"
    
    if old_step_counter in content:
        content = content.replace(old_step_counter, new_step_counter)
        fixes_applied.append("4. Updated step counter to use dynamic max")
    
    # =========================================================================
    # FIX 5: Reset limit state when coaching starts/ends
    # =========================================================================
    old_coaching_started = """        setState(() {
          _inPrivateCoaching = true;
          _showCoachingModal = false;  // Close any open modal
          _sanctuaryPaused = false;     // Not paused if we're IN coaching
          _coachingMessages = [];
          _coachingAttempt = 1;
        });"""
    
    new_coaching_started = """        setState(() {
          _inPrivateCoaching = true;
          _showCoachingModal = false;  // Close any open modal
          _sanctuaryPaused = false;     // Not paused if we're IN coaching
          _coachingMessages = [];
          _coachingAttempt = 1;
          _coachingLimitReached = false;
          _coachingMaxSteps = 5;
        });"""
    
    if old_coaching_started in content:
        content = content.replace(old_coaching_started, new_coaching_started)
        fixes_applied.append("5. Reset limit state when coaching starts")
    
    # =========================================================================
    # WRITE CHANGES
    # =========================================================================
    if fixes_applied:
        with open(FILE_PATH, 'w') as f:
            f.write(content)
        
        print("")
        print("✅ FIXES APPLIED:")
        for fix in fixes_applied:
            print(f"   • {fix}")
        
        print("")
        print("FLUTTER FLOW NOW:")
        print("  Step 1-5: Normal coaching, shows 'Step X/5'")
        print("  Step 6: Receives 'sanctuary_coaching_limit_reached'")
        print("          Shows dialog with 3 options:")
        print("          • Return to Family (free)")
        print("          • Get Help + Return ($3)")
        print("          • Continue Coaching ($5)")
        print("")
        print("NEXT: Hot restart Flutter")
    else:
        print("⚠️  No fixes applied")
    
    return True

if __name__ == "__main__":
    apply_fixes()
