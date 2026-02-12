#!/usr/bin/env python3
"""
Fix Stale Coaching Sessions
============================
1. Cleans up any orphaned coaching sessions
2. Resets sanctuary status if no active coaching

Run from: ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/
Usage: python3 fix_stale_coaching.py
"""

import json
import os
from datetime import datetime

DATA_FILE = "data/family_sanctuaries.json"

def fix_stale_sessions():
    print("=" * 60)
    print("FIXING STALE COACHING SESSIONS")
    print("=" * 60)
    
    if not os.path.exists(DATA_FILE):
        print(f"❌ File not found: {DATA_FILE}")
        return
    
    with open(DATA_FILE, 'r') as f:
        data = json.load(f)
    
    changes_made = False
    
    for sanctuary_id, sanctuary in data.get("active_sanctuaries", {}).items():
        print(f"\n📦 Checking sanctuary: {sanctuary_id}")
        print(f"   Status: {sanctuary.get('status')}")
        
        # Check for coaching_sessions
        coaching_sessions = sanctuary.get("coaching_sessions", {})
        active_sessions = [k for k, v in coaching_sessions.items() if v.get("status") == "ACTIVE"]
        
        print(f"   Coaching sessions: {len(coaching_sessions)} total, {len(active_sessions)} active")
        
        # If status is COACHING_ACTIVE but no active sessions, reset
        if sanctuary.get("status") == "COACHING_ACTIVE" and not active_sessions:
            print(f"   ⚠️  Status is COACHING_ACTIVE but no active sessions found!")
            sanctuary["status"] = "ACTIVE"
            
            # Also reset member statuses
            for member in sanctuary.get("members", []):
                if member.get("status") == "IN_COACHING":
                    print(f"   🔄 Resetting {member.get('name')} from IN_COACHING to ACTIVE")
                    member["status"] = "ACTIVE"
            
            # Clear orphaned coaching sessions
            if coaching_sessions:
                print(f"   🗑️  Clearing {len(coaching_sessions)} orphaned coaching sessions")
                sanctuary["coaching_sessions"] = {}
            
            changes_made = True
            print(f"   ✅ Reset sanctuary status to ACTIVE")
        
        # If there ARE active sessions, list them
        elif active_sessions:
            print(f"   Active sessions for: {active_sessions}")
            for session_id in active_sessions:
                session = coaching_sessions[session_id]
                print(f"      - {session.get('member_name')}: started {session.get('started_at')}")
    
    if changes_made:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        print("\n✅ Changes saved to family_sanctuaries.json")
    else:
        print("\n✅ No stale sessions found - data looks clean")
    
    print("\n" + "=" * 60)
    print("NEXT: Restart backend and test")
    print("=" * 60)

if __name__ == "__main__":
    fix_stale_sessions()
