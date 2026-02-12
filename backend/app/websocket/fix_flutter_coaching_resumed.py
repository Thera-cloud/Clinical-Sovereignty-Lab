#!/usr/bin/env python3
"""
Flutter Fix: Add handler for sanctuary_coaching_resumed
Run from: ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/
(or anywhere - it uses absolute path)
"""

import os
import shutil
from datetime import datetime

# Use absolute path to main.dart
FILE_PATH = os.path.expanduser("~/Desktop/Clinical-Sovereignty-Lab-2/mobile/lib/main.dart")

OLD_CODE = '''        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(data['message'] ?? 'Private coaching started'), backgroundColor: Colors.blue),
        );
        break;
      
      // COACHING RESPONSE from Little Nate
      case 'sanctuary_coaching_response':'''

NEW_CODE = '''        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(data['message'] ?? 'Private coaching started'), backgroundColor: Colors.blue),
        );
        break;
      
      // COACHING RESUMED - User reconnected while in coaching session
      case 'sanctuary_coaching_resumed':
        print('>>> SANCTUARY: Resuming private coaching session');
        setState(() {
          _inPrivateCoaching = true;
        });
        final resumeSession = data['coaching_session'];
        if (resumeSession != null) {
          final resumeMessages = resumeSession['messages'] as List<dynamic>? ?? [];
          setState(() {
            _coachingMessages = resumeMessages.map((m) => {
              'role': m['role'] ?? 'assistant',
              'content': m['content'] ?? '',
              'attempt': m['attempt_number'] ?? 1,
            }).toList();
            _coachingAttempt = resumeSession['attempt_number'] ?? 1;
          });
        }
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(data['message'] ?? 'Resuming coaching session'), backgroundColor: Colors.blue),
        );
        break;
      
      // COACHING RESPONSE from Little Nate
      case 'sanctuary_coaching_response':'''

def apply_fix():
    print("=" * 60)
    print("Flutter Fix: Add sanctuary_coaching_resumed handler")
    print("=" * 60)
    
    if not os.path.exists(FILE_PATH):
        print(f"❌ File not found: {FILE_PATH}")
        return False
    
    # Backup
    backup_path = FILE_PATH + f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy(FILE_PATH, backup_path)
    print(f"📦 Backup created: {backup_path}")
    
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
    
    print("✅ Fix applied to main.dart!")
    print("")
    print("NEXT: Hot restart Flutter (press 'r' or Cmd+S)")
    return True

if __name__ == "__main__":
    apply_fix()
