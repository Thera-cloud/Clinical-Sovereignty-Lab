#!/usr/bin/env python3
"""
Flutter Fix: Null Member Error + Load History on Rejoin
========================================================
Issues:
1. sanctuary_member_returned crashes when member is null
2. sanctuary_rejoined doesn't load message history

Run from anywhere (uses absolute path)
"""

import os
import shutil
from datetime import datetime

FILE_PATH = os.path.expanduser("~/Desktop/Clinical-Sovereignty-Lab-2/mobile/lib/main.dart")

def apply_fixes():
    print("=" * 60)
    print("Flutter Fix: Null Member + History on Rejoin")
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
    # FIX 1: Fix sanctuary_member_returned null error
    # =========================================================================
    old_member_returned = """      case 'sanctuary_member_returned':
        final returnedMember = data['member'] as Map<String, dynamic>;
        _addSystemMessage('\${returnedMember['name']} has returned to the sanctuary');
        break;"""
    
    new_member_returned = """      case 'sanctuary_member_returned':
        // Null-safe: member data may not always be present
        final memberData = data['member'];
        String memberName = 'A member';
        if (memberData != null && memberData is Map<String, dynamic>) {
          memberName = memberData['name'] ?? 'A member';
        } else if (data['member_name'] != null) {
          memberName = data['member_name'];
        }
        _addSystemMessage(data['message'] ?? '\$memberName has returned to the sanctuary');
        break;"""
    
    if old_member_returned in content:
        content = content.replace(old_member_returned, new_member_returned)
        fixes_applied.append("1. Fixed sanctuary_member_returned null error")
    else:
        # Try alternate pattern
        alt_old = "final returnedMember = data['member'] as Map<String, dynamic>;"
        if alt_old in content:
            print("   ⚠️  Found alternate pattern - manual fix may be needed")
        else:
            print("   ℹ️  sanctuary_member_returned may already be fixed")
    
    # =========================================================================
    # FIX 2: Load message history on sanctuary_rejoined
    # =========================================================================
    old_rejoined = """      case 'sanctuary_rejoined':
        setState(() {
          _sanctuaryId = data['sanctuary_id'];
          _sanctuaryStatus = data['status'] ?? 'ACTIVE';
          _members = _parseMembersList(data['members']);
        });
        _addSystemMessage(data['message'] ?? 'Welcome back!');
        _showSuccess('Welcome back to the sanctuary!');
        break;"""
    
    new_rejoined = """      case 'sanctuary_rejoined':
        setState(() {
          _sanctuaryId = data['sanctuary_id'];
          _sanctuaryStatus = data['status'] ?? 'ACTIVE';
          _members = _parseMembersList(data['members']);
        });
        // Load message history if provided
        final rejoinMessages = data['messages'] as List<dynamic>? ?? [];
        if (rejoinMessages.isNotEmpty) {
          setState(() {
            _messages = rejoinMessages.map((m) => Map<String, dynamic>.from(m)).toList();
          });
        }
        _addSystemMessage(data['message'] ?? 'Welcome back!');
        _showSuccess('Welcome back to the sanctuary!');
        break;"""
    
    if old_rejoined in content:
        content = content.replace(old_rejoined, new_rejoined)
        fixes_applied.append("2. Added message history loading on rejoin")
    else:
        print("   ⚠️  Could not find sanctuary_rejoined handler to update")
    
    # =========================================================================
    # FIX 3: Also ensure sanctuary_reconnected loads history properly
    # =========================================================================
    old_reconnected = """      case 'sanctuary_reconnected':
        setState(() {
          _sanctuaryId = data['sanctuary_id'];
          _sanctuaryStatus = data['status'] ?? 'ACTIVE';
          _members = _parseMembersList(data['members']);
        });
        _addSystemMessage(data['message'] ?? 'Reconnected to sanctuary');
        break;"""
    
    new_reconnected = """      case 'sanctuary_reconnected':
        setState(() {
          _sanctuaryId = data['sanctuary_id'];
          _sanctuaryStatus = data['status'] ?? 'ACTIVE';
          _members = _parseMembersList(data['members']);
        });
        // Load message history if provided
        final reconnectMessages = data['messages'] as List<dynamic>? ?? [];
        if (reconnectMessages.isNotEmpty) {
          setState(() {
            _messages = reconnectMessages.map((m) => Map<String, dynamic>.from(m)).toList();
          });
        }
        _addSystemMessage(data['message'] ?? 'Reconnected to sanctuary');
        break;"""
    
    if old_reconnected in content:
        content = content.replace(old_reconnected, new_reconnected)
        fixes_applied.append("3. Added message history loading on reconnect")
    else:
        print("   ℹ️  sanctuary_reconnected may already load history")
    
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
        print("NEXT: Hot restart Flutter")
    else:
        print("⚠️  No fixes applied - code may have changed")
    
    return True

if __name__ == "__main__":
    apply_fixes()
