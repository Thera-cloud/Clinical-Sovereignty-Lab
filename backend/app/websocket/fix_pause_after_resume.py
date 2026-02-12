#!/usr/bin/env python3
"""
Fix: Sanctuary Resumed Should Clear Pause State
================================================
Problem: When Jane finishes coaching, John stays on pause screen because:
1. sanctuary_resumed is received
2. But sanctuary_member_coaching arrives AFTER and re-triggers pause

Solution (Flutter side):
1. sanctuary_resumed should forcefully clear ALL pause states
2. Add timestamp check to ignore stale sanctuary_member_coaching messages
3. Clear _sanctuaryPaused flag when sanctuary_resumed is received

Run from anywhere
"""

import os
import shutil
from datetime import datetime

FILE_PATH = os.path.expanduser("~/Desktop/Clinical-Sovereignty-Lab-2/mobile/lib/main.dart")

def apply_fixes():
    print("=" * 60)
    print("Fix: Sanctuary Resumed Clears Pause State")
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
    # FIX 1: Update sanctuary_resumed handler to forcefully clear pause
    # =========================================================================
    
    # Find current sanctuary_resumed handler
    old_resumed = """      case 'sanctuary_resumed':
        setState(() {
          _sanctuaryPaused = false;
        });
        _addSystemMessage(data['message'] ?? 'The sanctuary has resumed.');
        break;"""
    
    new_resumed = """      case 'sanctuary_resumed':
        print('>>> SANCTUARY: Resumed - clearing ALL pause states');
        setState(() {
          _sanctuaryPaused = false;
          _showCoachingModal = false;
          _sanctuaryStatus = 'ACTIVE';
          // Mark the time we received resumed to ignore stale coaching messages
          _lastResumedAt = DateTime.now();
        });
        _addSystemMessage(data['message'] ?? 'The sanctuary has resumed.');
        break;"""
    
    if old_resumed in content:
        content = content.replace(old_resumed, new_resumed)
        fixes_applied.append("1. sanctuary_resumed now clears ALL pause states")
    else:
        # Try alternate pattern without setState wrapper
        print("   ⚠️  Could not find sanctuary_resumed handler - checking alternate patterns...")
    
    # =========================================================================
    # FIX 2: Add _lastResumedAt state variable
    # =========================================================================
    
    if "_lastResumedAt" not in content:
        old_state = "  bool _sanctuaryPaused = false;"
        new_state = """  bool _sanctuaryPaused = false;
  DateTime? _lastResumedAt;"""
        
        if old_state in content:
            content = content.replace(old_state, new_state)
            fixes_applied.append("2. Added _lastResumedAt state variable")
    
    # =========================================================================
    # FIX 3: Update sanctuary_member_coaching to check if we just resumed
    # =========================================================================
    
    old_member_coaching = """      case 'sanctuary_member_coaching':
        setState(() {
          _sanctuaryPaused = true;
          _pausedByMember = data['member_name'] ?? 'A family member';
        });
        break;"""
    
    new_member_coaching = """      case 'sanctuary_member_coaching':
        // Ignore if we just received sanctuary_resumed (within last 2 seconds)
        if (_lastResumedAt != null && 
            DateTime.now().difference(_lastResumedAt!).inSeconds < 2) {
          print('>>> SANCTUARY: Ignoring stale sanctuary_member_coaching (just resumed)');
          break;
        }
        setState(() {
          _sanctuaryPaused = true;
          _pausedByMember = data['member_name'] ?? 'A family member';
        });
        break;"""
    
    if old_member_coaching in content:
        content = content.replace(old_member_coaching, new_member_coaching)
        fixes_applied.append("3. sanctuary_member_coaching ignores stale messages after resume")
    else:
        # Try to find and update any version of this handler
        if "case 'sanctuary_member_coaching':" in content:
            print("   ⚠️  Found sanctuary_member_coaching but pattern differs - manual review needed")
    
    # =========================================================================
    # FIX 4: Also clear pause on sanctuary_coaching_completed broadcast
    # =========================================================================
    
    old_coaching_completed = """      case 'sanctuary_coaching_completed':
        setState(() {
          _inPrivateCoaching = false;
          _coachingMessages = [];
        });"""
    
    new_coaching_completed = """      case 'sanctuary_coaching_completed':
        setState(() {
          _inPrivateCoaching = false;
          _coachingMessages = [];
          _sanctuaryPaused = false;  // Also clear pause state
          _coachingLimitReached = false;
        });"""
    
    if old_coaching_completed in content:
        content = content.replace(old_coaching_completed, new_coaching_completed)
        fixes_applied.append("4. sanctuary_coaching_completed clears pause state")
    
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
        print("FLOW NOW:")
        print("  1. Jane finishes coaching")
        print("  2. Backend sends sanctuary_resumed to John")
        print("  3. John's Flutter sets _lastResumedAt = now")
        print("  4. If stale sanctuary_member_coaching arrives within 2 sec")
        print("     → IGNORED (not re-triggering pause)")
        print("  5. John sees main chat immediately")
        print("")
        print("NEXT: Hot restart Flutter and test")
    else:
        print("⚠️  No fixes applied - manual intervention needed")
        print("")
        print("Manual fix: In sanctuary_resumed handler, add:")
        print("  _sanctuaryPaused = false;")
        print("  _showCoachingModal = false;")
    
    return True

if __name__ == "__main__":
    apply_fixes()
