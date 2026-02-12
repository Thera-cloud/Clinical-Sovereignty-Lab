"""
DEVICE PROTECTION MODULE
========================
Sovereign Sanctuary - Device Registration & Session Security

Features:
- Device registration on first login
- Tier-based device limits
- New device alerts
- Force logout capability
- Device management for premium users
"""

import json
import hashlib
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Tuple

DATA_DIR = Path(__file__).parent / "data"

# =============================================================================
# DEVICE LIMITS BY TIER
# =============================================================================
DEVICE_LIMITS = {
    "TRIAL": 1,
    "STANDARD": 1,
    "PREMIUM": 3,
    "PRO": 3,
    "TOP_TIER": 3,
    "TOP": 3,
    "FAMILY_DEPENDENT": 1,  # Each family member gets 1 device
}

# =============================================================================
# DEVICE REGISTRY MANAGEMENT
# =============================================================================

def get_device_registry_path() -> Path:
    return DATA_DIR / "device_registry.json"

def load_device_registry() -> Dict:
    """Load the device registry from disk."""
    path = get_device_registry_path()
    if path.exists():
        with open(path, 'r') as f:
            return json.load(f)
    return {}

def save_device_registry(registry: Dict):
    """Save the device registry to disk."""
    path = get_device_registry_path()
    with open(path, 'w') as f:
        json.dump(registry, f, indent=2, default=str)

def generate_device_fingerprint(hardware_id: str, user_agent: str = "", ip_address: str = "") -> str:
    """Generate a unique device fingerprint."""
    raw = f"{hardware_id}:{user_agent}:{ip_address}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]

# =============================================================================
# DEVICE VALIDATION & REGISTRATION
# =============================================================================

def get_user_devices(user_id: str) -> List[Dict]:
    """Get all registered devices for a user."""
    registry = load_device_registry()
    return registry.get(user_id, {}).get("devices", [])

def get_device_limit(tier: str, subscription_plan: str = "") -> int:
    """Get the device limit for a user's tier."""
    # Check subscription plan first, then tier
    plan_upper = subscription_plan.upper() if subscription_plan else ""
    tier_upper = tier.upper() if tier else "STANDARD"
    
    if plan_upper in DEVICE_LIMITS:
        return DEVICE_LIMITS[plan_upper]
    return DEVICE_LIMITS.get(tier_upper, 1)

def validate_device(
    user_id: str,
    hardware_id: str,
    tier: str,
    subscription_plan: str = "",
    device_name: str = "Unknown Device",
    user_agent: str = "",
    ip_address: str = ""
) -> Tuple[bool, str, Optional[str]]:
    """
    Validate if a device can access this account.
    
    Returns:
        (is_valid, message, session_token or None)
    """
    registry = load_device_registry()
    user_devices = registry.get(user_id, {}).get("devices", [])
    device_limit = get_device_limit(tier, subscription_plan)
    
    # Generate fingerprint for this device
    fingerprint = generate_device_fingerprint(hardware_id, user_agent, ip_address)
    
    # Check if this device is already registered
    for device in user_devices:
        if device.get("hardware_id") == hardware_id or device.get("fingerprint") == fingerprint:
            # Device is registered - update last seen and return success
            device["last_seen"] = datetime.now().isoformat()
            device["login_count"] = device.get("login_count", 0) + 1
            save_device_registry(registry)
            
            # Generate session token
            session_token = secrets.token_hex(32)
            return True, "DEVICE_RECOGNIZED", session_token
    
    # Device is NOT registered - check if we can add it
    if len(user_devices) >= device_limit:
        # At device limit - cannot add new device
        device_names = [d.get("device_name", "Unknown") for d in user_devices]
        return False, f"DEVICE_LIMIT_REACHED|{device_limit}|{','.join(device_names)}", None
    
    # Can register new device
    new_device = {
        "device_id": secrets.token_hex(8),
        "hardware_id": hardware_id,
        "fingerprint": fingerprint,
        "device_name": device_name,
        "registered_at": datetime.now().isoformat(),
        "last_seen": datetime.now().isoformat(),
        "login_count": 1,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "is_active": True
    }
    
    # Initialize user entry if needed
    if user_id not in registry:
        registry[user_id] = {"devices": [], "alerts": []}
    
    registry[user_id]["devices"].append(new_device)
    
    # Add alert for new device registration
    registry[user_id]["alerts"].append({
        "type": "NEW_DEVICE_REGISTERED",
        "device_name": device_name,
        "timestamp": datetime.now().isoformat(),
        "ip_address": ip_address
    })
    
    save_device_registry(registry)
    
    # Generate session token
    session_token = secrets.token_hex(32)
    return True, "DEVICE_REGISTERED", session_token

def remove_device(user_id: str, device_id: str) -> Tuple[bool, str]:
    """Remove a device from user's registered devices."""
    registry = load_device_registry()
    
    if user_id not in registry:
        return False, "USER_NOT_FOUND"
    
    user_devices = registry[user_id].get("devices", [])
    original_count = len(user_devices)
    
    registry[user_id]["devices"] = [
        d for d in user_devices if d.get("device_id") != device_id
    ]
    
    if len(registry[user_id]["devices"]) == original_count:
        return False, "DEVICE_NOT_FOUND"
    
    # Add removal alert
    registry[user_id]["alerts"].append({
        "type": "DEVICE_REMOVED",
        "device_id": device_id,
        "timestamp": datetime.now().isoformat()
    })
    
    save_device_registry(registry)
    return True, "DEVICE_REMOVED"

def force_logout_all_devices(user_id: str) -> Tuple[bool, str]:
    """Force logout from all devices (invalidate all sessions)."""
    registry = load_device_registry()
    
    if user_id not in registry:
        return False, "USER_NOT_FOUND"
    
    # Mark all devices as requiring re-authentication
    for device in registry[user_id].get("devices", []):
        device["force_reauth"] = True
        device["reauth_timestamp"] = datetime.now().isoformat()
    
    # Add alert
    registry[user_id]["alerts"].append({
        "type": "FORCE_LOGOUT_ALL",
        "timestamp": datetime.now().isoformat()
    })
    
    save_device_registry(registry)
    return True, "ALL_DEVICES_LOGGED_OUT"

def check_session_valid(user_id: str, hardware_id: str, session_token: str) -> bool:
    """Check if a session is still valid (not force-logged-out)."""
    registry = load_device_registry()
    
    if user_id not in registry:
        return False
    
    for device in registry[user_id].get("devices", []):
        if device.get("hardware_id") == hardware_id:
            # Check if force reauth is required
            if device.get("force_reauth", False):
                return False
            return True
    
    return False

# =============================================================================
# SUSPICIOUS ACTIVITY DETECTION
# =============================================================================

def detect_suspicious_activity(
    user_id: str,
    hardware_id: str,
    ip_address: str
) -> List[str]:
    """
    Detect suspicious login patterns.
    Returns list of warning flags.
    """
    warnings = []
    registry = load_device_registry()
    
    if user_id not in registry:
        return warnings
    
    user_data = registry[user_id]
    devices = user_data.get("devices", [])
    
    # Check for rapid device switching
    recent_logins = []
    for device in devices:
        last_seen = device.get("last_seen", "")
        if last_seen:
            try:
                last_dt = datetime.fromisoformat(last_seen)
                if datetime.now() - last_dt < timedelta(hours=1):
                    recent_logins.append(device)
            except:
                pass
    
    if len(recent_logins) > 2:
        warnings.append("RAPID_DEVICE_SWITCHING")
    
    # Check for login from new IP with existing device
    for device in devices:
        if device.get("hardware_id") == hardware_id:
            if device.get("ip_address") and device.get("ip_address") != ip_address:
                warnings.append("IP_ADDRESS_CHANGED")
    
    # Log warnings
    if warnings:
        user_data.setdefault("alerts", []).append({
            "type": "SUSPICIOUS_ACTIVITY",
            "warnings": warnings,
            "timestamp": datetime.now().isoformat(),
            "ip_address": ip_address,
            "hardware_id": hardware_id
        })
        save_device_registry(registry)
    
    return warnings

# =============================================================================
# ADMIN FUNCTIONS
# =============================================================================

def admin_get_all_devices() -> Dict:
    """Get all registered devices (for admin dashboard)."""
    return load_device_registry()

def admin_get_user_devices(user_id: str) -> Dict:
    """Get devices for a specific user."""
    registry = load_device_registry()
    return registry.get(user_id, {"devices": [], "alerts": []})

def admin_force_remove_device(user_id: str, device_id: str) -> Tuple[bool, str]:
    """Admin force remove a device."""
    return remove_device(user_id, device_id)

def admin_reset_user_devices(user_id: str) -> Tuple[bool, str]:
    """Admin reset all devices for a user (fresh start)."""
    registry = load_device_registry()
    
    if user_id in registry:
        old_devices = registry[user_id].get("devices", [])
        registry[user_id] = {
            "devices": [],
            "alerts": [{
                "type": "ADMIN_DEVICE_RESET",
                "timestamp": datetime.now().isoformat(),
                "old_device_count": len(old_devices)
            }]
        }
        save_device_registry(registry)
        return True, f"RESET_COMPLETE|{len(old_devices)}_DEVICES_REMOVED"
    
    return False, "USER_NOT_FOUND"

# =============================================================================
# WEBSOCKET HANDLER INTEGRATION
# =============================================================================

def handle_device_validation(user_id: str, profile: Dict, hardware_id: str, 
                             ip_address: str = "", user_agent: str = "") -> Dict:
    """
    Main entry point for device validation during login.
    Returns a response dict to send back to client.
    """
    tier = profile.get("tier", "STANDARD")
    subscription_plan = profile.get("subscription_plan", "")
    device_name = f"Device_{hardware_id[:8]}"
    
    is_valid, message, session_token = validate_device(
        user_id=user_id,
        hardware_id=hardware_id,
        tier=tier,
        subscription_plan=subscription_plan,
        device_name=device_name,
        user_agent=user_agent,
        ip_address=ip_address
    )
    
    if not is_valid:
        # Parse the error message
        parts = message.split("|")
        error_type = parts[0]
        
        if error_type == "DEVICE_LIMIT_REACHED":
            limit = parts[1] if len(parts) > 1 else "1"
            existing_devices = parts[2] if len(parts) > 2 else ""
            
            return {
                "type": "device_blocked",
                "success": False,
                "reason": "DEVICE_LIMIT_REACHED",
                "message": f"Your {tier} plan allows {limit} device(s). You must remove an existing device to login here.",
                "device_limit": int(limit),
                "existing_devices": existing_devices.split(",") if existing_devices else [],
                "upgrade_available": tier in ["TRIAL", "STANDARD"]
            }
    
    # Check for suspicious activity
    warnings = detect_suspicious_activity(user_id, hardware_id, ip_address)
    
    return {
        "type": "device_validated",
        "success": True,
        "status": message,
        "session_token": session_token,
        "warnings": warnings,
        "is_new_device": message == "DEVICE_REGISTERED"
    }

# =============================================================================
# INITIALIZE
# =============================================================================

def initialize_device_registry():
    """Ensure the device registry file exists."""
    path = get_device_registry_path()
    if not path.exists():
        save_device_registry({})
        print(f"[DEVICE] Created device registry at {path}")

# Auto-initialize on import
initialize_device_registry()
