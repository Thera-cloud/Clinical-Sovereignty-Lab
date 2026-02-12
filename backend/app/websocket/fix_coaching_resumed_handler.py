#!/usr/bin/env python3
"""
Flutter Fix: Add handler for sanctuary_coaching_resumed
========================================================
When a user reconnects while they were in a coaching session,
the backend sends 'sanctuary_coaching_resumed' but Flutter
doesn't handle it, so the user sees the main chat instead of
their coaching session.

Run from: ~/Desktop/Clinical-Sovereignty-Lab-2/mobile/lib/
Usage: python3 fix_coaching_resumed_handler.py
"""

FILE_PATH = "main.dart"

# Find the coaching_started case and add coaching_resumed right after it
OLD_CODE = '''      case 'sanctuary_coaching_started':
        print('>>> SANCTUARY: Entering private coaching');
        setState(() {
          _inPrivateCoaching = true;
          _coachingMessages = [];
          _coachingAttempt = 1;
        });
        // Add Little Nate's first message
        final startMsg = data['coaching_message'];
        if (startMsg != null) {
          setState(() {
            _coachingMessages.add({
              'role': startMsg['role'] ?? 'assistant',
              'content': startMsg['content'] ?? '',
              'attempt': startMsg['attempt_number'] ?? 1,
            });
          });
        }
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(data['message'] ?? 'Private coaching started'), backgroundColor: Colors.blue),
        );
        break;'''

NEW_CODE = '''      case 'sanctuary_coaching_started':
        print('>>> SANCTUARY: Entering private coaching');
        setState(() {
          _inPrivateCoaching = true;
          _coachingMessages = [];
          _coachingAttempt = 1;
        });
        // Add Little Nate's first message
        final startMsg = data['coaching_message'];
        if (startMsg != null) {
          setState(() {
            _coachingMessages.add({
              'role': startMsg['role'] ?? 'assistant',
              'content': startMsg['content'] ?? '',
              'attempt': startMsg['attempt_number'] ?? 1,
            });
          });
        }
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(data['message'] ?? 'Private coaching started'), backgroundColor: Colors.blue),
        );
        break;
      
      // COACHING RESUMED - User reconnected while in coaching session
      case 'sanctuary_coaching_resumed':
        print('>>> SANCTUARY: Resuming private coaching session');
        setState(() {
          _inPrivateCoaching = true;
        });
        // Restore coaching messages from session data if available
        final session = data['coaching_session'];
        if (session != null) {
          final messages = session['messages'] as List<dynamic>? ?? [];
          setState(() {
            _coachingMessages = messages.map((m) => {
              'role': m['role'] ?? 'assistant',
              'content': m['content'] ?? '',
              'attempt': m['attempt_number'] ?? 1,
            }).toList();
            _coachingAttempt = session['attempt_number'] ?? 1;
          });
        }
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(data['message'] ?? 'Resuming coaching session'), backgroundColor: Colors.blue),
        );
        break;'''

def apply_fix():
    print("=" * 60)
    print("Flutter Fix: Add sanctuary_coaching_resumed handler")
    print("=" * 60)
    
    with open(FILE_PATH, 'r') as f:
        content = f.read()
    
    if "case 'sanctuary_coaching_resumed':" in content:
        print("⚠️  Fix already applied!")
        return False
    
    if OLD_CODE not in content:
        print("❌ Could not find the target code.")
        print("   The sanctuary_coaching_started handler may have changed.")
        return False
    
    content = content.replace(OLD_CODE, NEW_CODE)
    
    with open(FILE_PATH, 'w') as f:
        f.write(content)
    
    print("✅ Fix applied!")
    print("")
    print("Now when user reconnects while in coaching:")
    print("  • Backend sends: sanctuary_coaching_resumed")
    print("  • Flutter sets: _inPrivateCoaching = true")
    print("  • User sees: Private coaching UI (not main chat)")
    print("")
    print("NEXT: Hot restart Flutter (press 'r' or Cmd+S)")
    return True

if __name__ == "__main__":
    apply_fix()
