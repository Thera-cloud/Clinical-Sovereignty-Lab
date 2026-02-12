#!/usr/bin/env python3
"""
DASHBOARD HANDLERS PATCH
========================
Run this to add dashboard handlers to bridge_server.py

Usage: python3 patch_dashboard_handlers.py
"""

from pathlib import Path

BRIDGE_PATH = Path(__file__).parent / "bridge_server.py"

HANDLERS = '''
            # =================================================================
            # DASHBOARD HANDLERS (Added by patch)
            # =================================================================
            
            # === ADMIN: GET ALL USERS ===
            elif t == "admin_get_users":
                if current_profile and current_profile.get("role") in ["ADMIN", "COACH"]:
                    registry = load_json_file(REGISTRY_FILE, {})
                    users = []
                    for username, user_data in registry.items():
                        users.append({
                            "id": user_data.get("hardware_id", username),
                            "username": username,
                            "name": user_data.get("name", username),
                            "role": user_data.get("role", "CLIENT"),
                            "tier": user_data.get("tier", "STANDARD"),
                            "subscription_status": user_data.get("subscription_status", "active"),
                            "risk_level": user_data.get("metrics", {}).get("risk_level", "LOW"),
                            "last_login": user_data.get("last_login", "")
                        })
                    await websocket.send(json.dumps({
                        "type": "admin_users",
                        "users": users
                    }))

            # === COACH: GET ASSIGNED CLIENTS ===
            elif t == "coach_get_clients":
                if current_profile:
                    registry = load_json_file(REGISTRY_FILE, {})
                    clients = []
                    for username, user_data in registry.items():
                        if user_data.get("role") == "CLIENT":
                            clients.append({
                                "id": user_data.get("hardware_id", username),
                                "username": username,
                                "name": user_data.get("name", username),
                                "tier": user_data.get("tier", "STANDARD"),
                                "last_login": user_data.get("last_login", ""),
                                "metrics": user_data.get("metrics", {}),
                                "assigned_coach": user_data.get("assigned_coach", "")
                            })
                    await websocket.send(json.dumps({
                        "type": "coach_clients",
                        "clients": clients
                    }))

            # === FETCH COACH CALENDAR ===
            elif t == "fetch_coach_calendar":
                if current_profile:
                    await websocket.send(json.dumps({
                        "type": "coach_calendar_data",
                        "data": {"schedule": []}
                    }))

            # === ADMIN: GET CRISIS WATCHLIST ===
            elif t == "admin_get_crisis_watchlist":
                if current_profile and current_profile.get("role") in ["ADMIN", "COACH"]:
                    try:
                        watchlist = analytics_engine.get_crisis_watchlist()
                    except:
                        watchlist = []
                    await websocket.send(json.dumps({
                        "type": "crisis_watchlist",
                        "watchlist": watchlist
                    }))

            # === ADMIN: GET PENDING COACHES ===
            elif t == "admin_get_pending_coaches":
                if current_profile and current_profile.get("role") == "ADMIN":
                    await websocket.send(json.dumps({
                        "type": "pending_coaches",
                        "coaches": []
                    }))

            # === ASK NATE (COACHING CONTEXT) ===
            elif t == "ask_nate_coaching":
                if current_profile:
                    query = d.get("query", "")
                    client_id = d.get("client_id", "")
                    coaching_prompt = f"[COACHING QUERY about client {client_id}]: {query}" if client_id else query
                    await cortex.process_interaction(current_profile, coaching_prompt)

            # === GET PRE-SESSION BRIEF ===
            elif t == "get_presession_brief":
                if current_profile:
                    client_id = d.get("client_id", "")
                    registry = load_json_file(REGISTRY_FILE, {})
                    client_data = None
                    for username, data in registry.items():
                        if data.get("hardware_id") == client_id or username == client_id:
                            client_data = data
                            client_data["username"] = username
                            break
                    if client_data:
                        try:
                            memories = hippocampus.recall_full(client_data, limit=5)
                        except:
                            memories = []
                        brief = {
                            "client": {
                                "name": client_data.get("name", "Client"),
                                "tier": client_data.get("tier", "STANDARD"),
                                "total_sessions": client_data.get("total_sessions", 0),
                                "joined_date": client_data.get("joined_date", "Unknown")
                            },
                            "metrics": client_data.get("metrics", {}),
                            "recent_topics": [],
                            "breakthroughs": [],
                            "family_members": [],
                            "recent_conversations": memories,
                            "nate_suggestion": "Based on recent sessions, I recommend checking in about their current emotional state."
                        }
                        await websocket.send(json.dumps({"type": "presession_brief", "brief": brief}))
                    else:
                        await websocket.send(json.dumps({"type": "error", "message": "Client not found"}))

'''

def patch():
    if not BRIDGE_PATH.exists():
        print(f"[ERROR] bridge_server.py not found at {BRIDGE_PATH}")
        return False
    
    with open(BRIDGE_PATH, 'r') as f:
        content = f.read()
    
    # Check if already patched
    if "admin_get_users" in content:
        print("[INFO] Dashboard handlers already present. Skipping.")
        return True
    
    # Find insertion point (before the except block)
    marker = "    except websockets.exceptions.ConnectionClosed:"
    
    if marker not in content:
        print("[ERROR] Could not find insertion point")
        return False
    
    # Create backup
    backup = BRIDGE_PATH.with_suffix('.py.dashboard_backup')
    with open(backup, 'w') as f:
        f.write(content)
    print(f"[✓] Backup created: {backup}")
    
    # Insert handlers
    content = content.replace(marker, HANDLERS + marker)
    
    with open(BRIDGE_PATH, 'w') as f:
        f.write(content)
    
    print(f"[✓] Dashboard handlers added to {BRIDGE_PATH}")
    print("\n[SUCCESS] Restart bridge_server.py to apply changes")
    return True

if __name__ == "__main__":
    patch()
