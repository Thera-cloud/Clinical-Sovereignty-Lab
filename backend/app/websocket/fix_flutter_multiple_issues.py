#!/usr/bin/env python3
"""
Flutter Fixes: Multiple Sanctuary Issues
=========================================
1. Fix null error in sanctuary_member_returned
2. Add handler for sanctuary_assisted_response_generated  
3. Ensure _showCoachingModal is closed when coaching starts

Run from anywhere (uses absolute path)
"""

import os
import shutil
from datetime import datetime

FILE_PATH = os.path.expanduser("~/Desktop/Clinical-Sovereignty-Lab-2/mobile/lib/main.dart")

def apply_fixes():
    print("=" * 60)
    print("Flutter Fixes: Multiple Sanctuary Issues")
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
    # FIX 1: sanctuary_member_returned null check
    # =========================================================================
    old_member_returned = "      case 'sanctuary_member_returned':\n        _addSystemMessage(data['message'] ?? 'A member has returned');\n        break;"
    
    new_member_returned = """      case 'sanctuary_member_returned':
        // Null-safe: data might not have 'member' key
        if (data != null) {
          final memberData = data['member'];
          final memberName = memberData != null ? memberData['name'] ?? 'A member' : 'A member';
          _addSystemMessage(data['message'] ?? '\$memberName has returned to the sanctuary');
        }
        break;"""
    
    # Try alternative pattern if first doesn't match
    old_member_returned_alt = """      case 'sanctuary_member_returned':
        _addSystemMessage(data['message'] ?? 'A member has returned');
        break;"""
    
    if old_member_returned in content:
        content = content.replace(old_member_returned, new_member_returned)
        fixes_applied.append("1. Fixed sanctuary_member_returned null check")
    elif old_member_returned_alt in content:
        content = content.replace(old_member_returned_alt, new_member_returned)
        fixes_applied.append("1. Fixed sanctuary_member_returned null check")
    else:
        print("   ⚠️  Could not find sanctuary_member_returned to fix")
    
    # =========================================================================
    # FIX 2: Add sanctuary_assisted_response_generated handler
    # =========================================================================
    if "sanctuary_assisted_response_generated" not in content:
        # Find where to insert - after sanctuary_coaching_response
        insert_marker = """      // COACHING COMPLETED - Return to sanctuary
      case 'sanctuary_coaching_completed':"""
        
        new_handler = """      // ASSISTED RESPONSE GENERATED
      case 'sanctuary_assisted_response_generated':
        print('>>> SANCTUARY: Assisted response received');
        final assistedResponse = data['assisted_response'] ?? data['response'] ?? '';
        if (assistedResponse.isNotEmpty) {
          setState(() {
            _coachingMessages.add({
              'role': 'assisted',
              'content': assistedResponse,
              'is_assisted': true,
            });
          });
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Assisted response ready - you can use this in the chat'), backgroundColor: Colors.green),
          );
        }
        break;
      
      // COACHING COMPLETED - Return to sanctuary
      case 'sanctuary_coaching_completed':"""
        
        if insert_marker in content:
            content = content.replace(insert_marker, new_handler)
            fixes_applied.append("2. Added sanctuary_assisted_response_generated handler")
        else:
            print("   ⚠️  Could not find insertion point for assisted_response handler")
    else:
        print("   ℹ️  sanctuary_assisted_response_generated handler already exists")
    
    # =========================================================================
    # FIX 3: Ensure coaching modal closes when coaching starts
    # =========================================================================
    old_coaching_started = """      case 'sanctuary_coaching_started':
        print('>>> SANCTUARY: Entering private coaching');
        setState(() {
          _inPrivateCoaching = true;
          _coachingMessages = [];
          _coachingAttempt = 1;
        });"""
    
    new_coaching_started = """      case 'sanctuary_coaching_started':
        print('>>> SANCTUARY: Entering private coaching');
        setState(() {
          _inPrivateCoaching = true;
          _showCoachingModal = false;  // Close any open modal
          _sanctuaryPaused = false;     // Not paused if we're IN coaching
          _coachingMessages = [];
          _coachingAttempt = 1;
        });"""
    
    if old_coaching_started in content:
        content = content.replace(old_coaching_started, new_coaching_started)
        fixes_applied.append("3. Fixed coaching_started to close modal and unpause")
    else:
        print("   ⚠️  Could not find sanctuary_coaching_started to update")
    
    # =========================================================================
    # FIX 4: Ensure coaching_resumed also sets proper state
    # =========================================================================
    old_coaching_resumed = """      case 'sanctuary_coaching_resumed':
        print('>>> SANCTUARY: Resuming private coaching session');
        setState(() {
          _inPrivateCoaching = true;
        });"""
    
    new_coaching_resumed = """      case 'sanctuary_coaching_resumed':
        print('>>> SANCTUARY: Resuming private coaching session');
        setState(() {
          _inPrivateCoaching = true;
          _showCoachingModal = false;  // Close any open modal
          _sanctuaryPaused = false;     // Not paused if we're IN coaching
        });"""
    
    if old_coaching_resumed in content:
        content = content.replace(old_coaching_resumed, new_coaching_resumed)
        fixes_applied.append("4. Fixed coaching_resumed to close modal and unpause")
    else:
        print("   ⚠️  Could not find sanctuary_coaching_resumed to update")
    
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
    else:
        print("")
        print("⚠️  No fixes were applied")
    
    print("")
    print("NEXT: Hot restart Flutter (press 'r' or Cmd+S)")
    return True

if __name__ == "__main__":
    apply_fixes()
