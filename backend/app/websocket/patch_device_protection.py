#!/usr/bin/env python3
"""
DEVICE PROTECTION INTEGRATION PATCH
====================================
Run this script to automatically patch bridge_server.py with device protection.

Usage:
    python3 patch_device_protection.py
"""

import re
from pathlib import Path

# Path to bridge_server.py
BRIDGE_SERVER_PATH = Path(__file__).parent / "bridge_server.py"

def patch_file():
    """Apply device protection patches to bridge_server.py"""
    
    if not BRIDGE_SERVER_PATH.exists():
        print(f"[ERROR] bridge_server.py not found at {BRIDGE_SERVER_PATH}")
        return False
    
    with open(BRIDGE_SERVER_PATH, 'r') as f:
        content = f.read()
    
    # Check if already patched
    if "device_protection" in content:
        print("[INFO] Device protection already integrated. Skipping.")
        return True
    
    # =========================================================================
    # PATCH 1: Add import at top
    # =========================================================================
    old_import = "from bridge_handlers_v2 import CoachNexusV2"
    new_import = """from bridge_handlers_v2 import CoachNexusV2
from device_protection import (
    handle_device_validation,
    get_user_devices,
    remove_device,
    force_logout_all_devices,
    get_device_limit,
    admin_get_user_devices,
    admin_reset_user_devices,
    detect_suspicious_activity
)"""
    
    if old_import in content:
        content = content.replace(old_import, new_import)
        print("[✓] Added device_protection import")
    else:
        print("[!] Could not find import location, adding at top")
        content = new_import.replace(old_import + "\n", "") + "\n" + content
    
    # =========================================================================
    # PATCH 2: Modify login_request handler
    # =========================================================================
    old_login = '''            if t == "login_request":
                tok, res = authenticate_user(d["username"], d["password"], d.get("expected_role"))
                if tok:
                    uid = res.get("hardware_id")
                    current_profile = res
                    cortex.register(uid, websocket)
                    analytics_engine.record_event("login", uid)
                    notification_system.register_connection(uid, websocket)  # ADD THIS LINE
                    await websocket.send(json.dumps({"type": "login_success", "token": tok, "profile": res}))
                else:
                    await websocket.send(json.dumps({"type": "login_failed", "message": res}))'''
    
    new_login = '''            if t == "login_request":
                tok, res = authenticate_user(d["username"], d["password"], d.get("expected_role"))
                if tok:
                    uid = res.get("hardware_id")
                    user_id = f"{res.get('role', 'CLIENT').lower()}_{d['username']}"
                    hardware_id = d.get("hardware_id", uid)
                    
                    # === DEVICE PROTECTION ===
                    device_result = handle_device_validation(
                        user_id=user_id,
                        profile=res,
                        hardware_id=hardware_id,
                        ip_address=websocket.remote_address[0] if hasattr(websocket, 'remote_address') else "",
                        user_agent=d.get("user_agent", "")
                    )
                    
                    if not device_result["success"]:
                        # Device blocked
                        await websocket.send(json.dumps({
                            "type": "login_failed",
                            "message": "DEVICE_BLOCKED",
                            "device_info": device_result
                        }))
                        continue
                    
                    # Device validated - proceed with login
                    current_profile = res
                    current_hardware_id = hardware_id
                    cortex.register(uid, websocket)
                    analytics_engine.record_event("login", uid)
                    notification_system.register_connection(uid, websocket)
                    
                    await websocket.send(json.dumps({
                        "type": "login_success", 
                        "token": tok, 
                        "profile": res,
                        "device_status": device_result.get("status", ""),
                        "is_new_device": device_result.get("is_new_device", False),
                        "session_token": device_result.get("session_token", "")
                    }))
                else:
                    await websocket.send(json.dumps({"type": "login_failed", "message": res}))'''
    
    if old_login in content:
        content = content.replace(old_login, new_login)
        print("[✓] Patched login_request handler with device validation")
    else:
        print("[!] Could not find exact login handler - manual integration may be needed")
    
    # =========================================================================
    # PATCH 3: Add variable initialization after connection
    # =========================================================================
    old_init = '''    uid = "GUEST"
    current_profile = None'''
    
    new_init = '''    uid = "GUEST"
    current_profile = None
    current_hardware_id = None'''
    
    if old_init in content:
        content = content.replace(old_init, new_init)
        print("[✓] Added current_hardware_id variable")
    
    # =========================================================================
    # PATCH 4: Add device management handlers (before the except block)
    # =========================================================================
    device_handlers = '''
            # =================================================================
            # DEVICE MANAGEMENT HANDLERS
            # =================================================================
            
            # === GET MY DEVICES ===
            elif t == "get_my_devices":
                if current_profile:
                    user_id = f"{current_profile.get('role', 'CLIENT').lower()}_{d.get('username', '')}"
                    if not user_id or user_id.endswith('_'):
                        # Reconstruct from uid
                        user_id = uid.replace('CLIENT_', 'client_').replace('COACH_', 'coach_').replace('ADMIN_', 'admin_')
                    
                    devices = get_user_devices(user_id)
                    tier = current_profile.get("tier", "STANDARD")
                    plan = current_profile.get("subscription_plan", "")
                    device_limit = get_device_limit(tier, plan)
                    
                    # Mark current device
                    req_hardware_id = d.get("hardware_id", current_hardware_id)
                    for device in devices:
                        device["is_current"] = device.get("hardware_id") == req_hardware_id
                    
                    await websocket.send(json.dumps({
                        "type": "my_devices",
                        "devices": devices,
                        "device_limit": device_limit
                    }))
            
            # === REMOVE DEVICE ===
            elif t == "remove_device":
                if current_profile:
                    user_id = f"{current_profile.get('role', 'CLIENT').lower()}_{d.get('username', '')}"
                    if not user_id or user_id.endswith('_'):
                        user_id = uid.replace('CLIENT_', 'client_').replace('COACH_', 'coach_').replace('ADMIN_', 'admin_')
                    
                    device_id = d.get("device_id", "")
                    success, message = remove_device(user_id, device_id)
                    
                    await websocket.send(json.dumps({
                        "type": "device_removed" if success else "device_remove_failed",
                        "success": success,
                        "message": message
                    }))
            
            # === LOGOUT ALL DEVICES ===
            elif t == "logout_all_devices":
                if current_profile:
                    user_id = f"{current_profile.get('role', 'CLIENT').lower()}_{d.get('username', '')}"
                    if not user_id or user_id.endswith('_'):
                        user_id = uid.replace('CLIENT_', 'client_').replace('COACH_', 'coach_').replace('ADMIN_', 'admin_')
                    
                    success, message = force_logout_all_devices(user_id)
                    
                    await websocket.send(json.dumps({
                        "type": "all_devices_logged_out" if success else "logout_failed",
                        "success": success,
                        "message": message
                    }))
            
            # === ADMIN: GET USER DEVICES ===
            elif t == "admin_get_user_devices":
                if current_profile and current_profile.get("role") == "ADMIN":
                    target_user_id = d.get("user_id", "")
                    devices_info = admin_get_user_devices(target_user_id)
                    
                    await websocket.send(json.dumps({
                        "type": "admin_user_devices",
                        "user_id": target_user_id,
                        "data": devices_info
                    }))
            
            # === ADMIN: RESET USER DEVICES ===
            elif t == "admin_reset_user_devices":
                if current_profile and current_profile.get("role") == "ADMIN":
                    target_user_id = d.get("user_id", "")
                    success, message = admin_reset_user_devices(target_user_id)
                    
                    await websocket.send(json.dumps({
                        "type": "admin_devices_reset",
                        "success": success,
                        "message": message,
                        "user_id": target_user_id
                    }))

'''
    
    # Find the location to insert (before the except block)
    insert_marker = '''    except websockets.exceptions.ConnectionClosed:'''
    
    if insert_marker in content:
        content = content.replace(insert_marker, device_handlers + insert_marker)
        print("[✓] Added device management handlers")
    else:
        print("[!] Could not find insertion point for device handlers")
    
    # =========================================================================
    # WRITE PATCHED FILE
    # =========================================================================
    
    # Create backup
    backup_path = BRIDGE_SERVER_PATH.with_suffix('.py.backup')
    with open(backup_path, 'w') as f:
        with open(BRIDGE_SERVER_PATH, 'r') as orig:
            f.write(orig.read())
    print(f"[✓] Created backup at {backup_path}")
    
    # Write patched file
    with open(BRIDGE_SERVER_PATH, 'w') as f:
        f.write(content)
    
    print(f"[✓] Patched {BRIDGE_SERVER_PATH}")
    print("\n[SUCCESS] Device protection integrated!")
    print("\nNext steps:")
    print("1. Make sure device_protection.py is in the same directory")
    print("2. Restart the bridge server: python3 bridge_server.py")
    
    return True

if __name__ == "__main__":
    patch_file()
