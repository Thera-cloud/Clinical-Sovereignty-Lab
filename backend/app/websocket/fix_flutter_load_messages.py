#!/usr/bin/env python3
"""
Flutter Fix: Load Message History from ALL Reconnect Scenarios
==============================================================
Ensures Flutter loads messages from:
- sanctuary_reconnected
- sanctuary_rejoined  
- sanctuary_joined

Run from anywhere
"""

import os
import shutil
from datetime import datetime

FILE_PATH = os.path.expanduser("~/Desktop/Clinical-Sovereignty-Lab-2/mobile/lib/main.dart")

def apply_fixes():
    print("=" * 60)
    print("Flutter Fix: Load Messages on Reconnect")
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
    # Helper function to add to all handlers
    # =========================================================================
    message_loader_code = '''
        // Load message history if provided
        final historyMessages = data['messages'] as List<dynamic>?;
        if (historyMessages != null && historyMessages.isNotEmpty) {
          setState(() {
            _messages = historyMessages.map((m) => Map<String, dynamic>.from(m as Map)).toList();
          });
          print('>>> SANCTUARY: Loaded ${historyMessages.length} messages from history');
        }'''
    
    # =========================================================================
    # FIX 1: sanctuary_reconnected - add message loading
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
        final reconnectMessages = data['messages'] as List<dynamic>?;
        if (reconnectMessages != null && reconnectMessages.isNotEmpty) {
          setState(() {
            _messages = reconnectMessages.map((m) => Map<String, dynamic>.from(m as Map)).toList();
          });
          print('>>> SANCTUARY: Loaded \${reconnectMessages.length} messages from history');
        }
        _addSystemMessage(data['message'] ?? 'Reconnected to sanctuary');
        break;"""
    
    if old_reconnected in content:
        content = content.replace(old_reconnected, new_reconnected)
        fixes_applied.append("1. sanctuary_reconnected now loads message history")
    
    # =========================================================================
    # FIX 2: sanctuary_rejoined - ensure message loading works
    # =========================================================================
    
    # Check if it already has message loading (from previous fix)
    if "rejoinMessages" not in content and "sanctuary_rejoined" in content:
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
        final rejoinMessages = data['messages'] as List<dynamic>?;
        if (rejoinMessages != null && rejoinMessages.isNotEmpty) {
          setState(() {
            _messages = rejoinMessages.map((m) => Map<String, dynamic>.from(m as Map)).toList();
          });
          print('>>> SANCTUARY: Loaded \${rejoinMessages.length} messages from history');
        }
        _addSystemMessage(data['message'] ?? 'Welcome back!');
        _showSuccess('Welcome back to the sanctuary!');
        break;"""
        
        if old_rejoined in content:
            content = content.replace(old_rejoined, new_rejoined)
            fixes_applied.append("2. sanctuary_rejoined now loads message history")
    else:
        print("   ℹ️  sanctuary_rejoined already has message loading")
    
    # =========================================================================
    # FIX 3: sanctuary_joined - add message loading for new members
    # =========================================================================
    
    old_joined = """      case 'sanctuary_joined':
        setState(() {
          _sanctuaryId = data['sanctuary_id'];
          _sanctuaryStatus = data['status'] ?? 'ACTIVE';
          _members = _parseMembersList(data['members']);
        });
        _showSuccess('Joined Family Sanctuary!');
        break;"""
    
    new_joined = """      case 'sanctuary_joined':
        setState(() {
          _sanctuaryId = data['sanctuary_id'];
          _sanctuaryStatus = data['status'] ?? 'ACTIVE';
          _members = _parseMembersList(data['members']);
        });
        // Load message history if provided (new member catches up)
        final joinMessages = data['messages'] as List<dynamic>?;
        if (joinMessages != null && joinMessages.isNotEmpty) {
          setState(() {
            _messages = joinMessages.map((m) => Map<String, dynamic>.from(m as Map)).toList();
          });
          print('>>> SANCTUARY: Loaded \${joinMessages.length} messages from history');
        }
        _showSuccess('Joined Family Sanctuary!');
        break;"""
    
    if old_joined in content:
        content = content.replace(old_joined, new_joined)
        fixes_applied.append("3. sanctuary_joined now loads message history")
    
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
        print("Flutter now loads messages from:")
        print("  • sanctuary_reconnected (page refresh)")
        print("  • sanctuary_rejoined (after exit)")
        print("  • sanctuary_joined (new member)")
        print("")
        print("NEXT: Hot restart Flutter")
    else:
        print("⚠️  No fixes applied - code patterns may have changed")
    
    return True

if __name__ == "__main__":
    apply_fixes()
