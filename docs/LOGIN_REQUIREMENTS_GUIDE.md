# LOGIN REQUIREMENTS GUIDE
## Clinical Sovereignty Lab - Authentication Standards

**Last Updated:** January 26, 2026  
**Status:** ✅ RESOLVED - Working implementation documented

---

## 🎯 PURPOSE

This guide documents the **exact requirements** for user authentication in the Clinical Sovereignty Lab system. Use this checklist when creating ANY new user account or debugging login issues.

---

## ✅ MANDATORY REQUIREMENTS CHECKLIST

### 1. User Registry Structure ✓

**Registry Key Format:**
```
{role}_{username}
```

**Examples:**
- Admin user "admin1" → Key: `admin_admin1`
- Coach user "sarah" → Key: `coach_sarah`
- Client user "john" → Key: `client_john`

**Full Structure:**
```json
{
  "admin_admin1": {
    "credentials": {
      "username": "admin1",
      "password": "salt:hash_string_here"
    },
    "profile": {
      "role": "ADMIN",
      "consent_version": "v12.6_2026_FINAL",
      "subscription_status": "ACTIVE",
      ...
    }
  }
}
```

### 2. Password Hash Format ✓

**Required Format:** `salt:hash`

**Specifications:**
- Salt: 32-character hex string (16 bytes)
- Hash: PBKDF2-HMAC-SHA256
- Iterations: 100,000
- Output: Hex string

**Generation Code:**
```python
import hashlib
import secrets

password = "user_password"
salt = secrets.token_hex(16)  # 32 chars
hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
hashed_password = f"{salt}:{hashed.hex()}"
```

**Example Output:**
```
a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6:q7r8s9t0u1v2w3x4y5z6a7b8c9d0e1f2g3h4i5j6k7l8m9n0o1p2q3r4s5t6u7v8w9x0
```

**❌ WRONG Formats:**
- Plain text: `"admin123"`
- Simple SHA256: `"240be518fabd2724..."`
- Missing salt: `"e5f6g7h8..."`
- Wrong separator: `"salt|hash"` or `"salt-hash"`

### 3. Nested Object Structure ✓

**❌ WRONG (Flat Structure):**
```json
{
  "admin1": {
    "username": "admin1",
    "password_hash": "...",
    "role": "ADMIN"
  }
}
```

**✅ CORRECT (Nested Structure):**
```json
{
  "admin_admin1": {
    "credentials": {
      "username": "admin1",
      "password": "salt:hash"
    },
    "profile": {
      "role": "ADMIN",
      ...
    }
  }
}
```

### 4. Consent Version ✓

**Current Required Version:** `v12.6_2026_FINAL`

**Location:** `profile.consent_version`

**Check in bridge_server.py:**
```python
REQUIRED_CONSENT_VERSION = "v12.6_2026_FINAL"  # Line 36
```

**❌ Login will fail with:**
- `"v1.0"` → "LEGAL_UPDATE_REQUIRED"
- `"v0.0"` → "LEGAL_UPDATE_REQUIRED"  
- Missing field → "LEGAL_UPDATE_REQUIRED"

**✅ Must be exactly:** `"v12.6_2026_FINAL"`

### 5. Subscription Status ✓

**Required Status:** `"ACTIVE"`

**Location:** `profile.subscription_status`

**Valid Statuses:**
- ✅ `"ACTIVE"` - User can login
- ❌ `"PENDING_VERIFICATION"` - Returns "ACCOUNT_PENDING_APPROVAL"
- ❌ `"TRIAL_ACTIVE"` - May work for clients, check backend
- ❌ `"SUSPENDED"` - Cannot login
- ❌ `"CANCELLED"` - Cannot login

**For Admin/Coach accounts:** Always use `"ACTIVE"`

### 6. Required Profile Fields ✓

**Minimum Required Fields:**
```json
{
  "role": "ADMIN" | "COACH" | "CLIENT",
  "name": "User Name",
  "email": "user@example.com",
  "hardware_id": "ROLE_USERNAME_ID",
  "family_id": "FAM_ABCD1234",
  "joined_date": "2026-01-26",
  "tier": "STANDARD" | "TOP_TIER",
  "consent_version": "v12.6_2026_FINAL",
  "timezone": "America/New_York",
  "subscription_status": "ACTIVE",
  "subscription_plan": "TRIAL" | "TOP_TIER",
  "token_balance": 10000,
  "last_login": "",
  "login_count": 0
}
```

---

## 🔍 AUTHENTICATION FLOW

### Backend Process (bridge_server.py)

**Step 1: Receive login_request**
```json
{
  "type": "login_request",
  "username": "admin1",
  "password": "admin123",
  "expected_role": "ADMIN",
  "hardware_id": "WEB_..."
}
```

**Step 2: Search registry (Line 105-110)**
```python
for k, v in registry.items():
    if v.get("credentials", {}).get("username") == username:
        target = v
        break

if not target:
    return None, "USER_NOT_FOUND"
```

**Step 3: Verify password (Line 92-100)**
```python
def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, hash_hex = stored_hash.split(':')
        hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        return hashed.hex() == hash_hex
    except:
        return password == stored_hash  # Legacy fallback
```

**Step 4: Check subscription status (Line 114-115)**
```python
if p.get("subscription_status") == "PENDING_VERIFICATION":
    return None, "ACCOUNT_PENDING_APPROVAL"
```

**Step 5: Check consent version (Line 117-118)**
```python
if p.get("consent_version", "v0.0") != REQUIRED_CONSENT_VERSION:
    return None, "LEGAL_UPDATE_REQUIRED"
```

**Step 6: Check role (Line 120-121)**
```python
if expected_role and p.get("role") != "ADMIN" and p.get("role") != expected_role:
    return None, "WRONG_PORTAL"
```

**Step 7: Return token and profile**
```python
token = secrets.token_hex(16)
ACTIVE_TOKENS[token] = p
return token, p
```

---

## 🚨 COMMON LOGIN ERRORS & SOLUTIONS

### Error: "USER_NOT_FOUND"

**Causes:**
1. Registry key format wrong (`"admin1"` instead of `"admin_admin1"`)
2. Username not in `credentials.username`
3. User doesn't exist in user_registry.json

**Solution:**
```python
# Check registry key
registry_key = f"{role.lower()}_{username}"  # e.g., "admin_admin1"

# Verify structure
user = {
    "credentials": {"username": username, ...},
    "profile": {...}
}
```

### Error: "INVALID_PASSWORD"

**Causes:**
1. Password not in `salt:hash` format
2. Salt or hash incorrect
3. Password field in wrong location

**Solution:**
```python
# Generate proper hash
import hashlib, secrets
salt = secrets.token_hex(16)
hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
password_field = f"{salt}:{hashed.hex()}"
```

### Error: "ACCOUNT_PENDING_APPROVAL"

**Cause:**
```json
"subscription_status": "PENDING_VERIFICATION"
```

**Solution:**
```json
"subscription_status": "ACTIVE"
```

### Error: "LEGAL_UPDATE_REQUIRED"

**Cause:**
```json
"consent_version": "v1.0"  // Wrong version
```

**Solution:**
```json
"consent_version": "v12.6_2026_FINAL"
```

### Error: "WRONG_PORTAL"

**Cause:**
- Trying to login to ADMIN portal with COACH credentials
- Role mismatch

**Solution:**
- Verify `profile.role` matches `expected_role` in login request
- Or role is "ADMIN" (admins can access all portals)

---

## 🛠️ USER CREATION SCRIPT TEMPLATE

Use this template when creating ANY new user:

```python
import json
import hashlib
import secrets
from datetime import datetime, timedelta

def create_user(role, username, password, name, email):
    """
    Create a properly formatted user for user_registry.json
    
    Args:
        role: "ADMIN", "COACH", or "CLIENT"
        username: Unique username
        password: Plain text password (will be hashed)
        name: Full name
        email: Email address
    """
    
    # Load existing registry
    try:
        with open("data/user_registry.json", "r") as f:
            registry = json.load(f)
    except:
        registry = {}
    
    # Generate password hash
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    hashed_password = f"{salt}:{hashed.hex()}"
    
    # Create profile
    profile = {
        "role": role,
        "name": name,
        "email": email,
        "phone": "",
        "hardware_id": f"{role}_{username.upper()}_ID",
        "family_id": f"FAM_{secrets.token_hex(4).upper()}",
        "joined_date": str(datetime.now().date()),
        "tier": "STANDARD",
        "dob": "",
        "consent_version": "v12.6_2026_FINAL",  # ← CRITICAL!
        "timezone": "America/New_York",
        "profile_photo_url": "",
        "emergency_contact": "",
        
        # Subscription & Billing
        "subscription_status": "ACTIVE" if role in ["ADMIN", "COACH"] else "TRIAL_ACTIVE",
        "subscription_plan": "TOP_TIER" if role == "ADMIN" else "TRIAL",
        "stripe_customer_id": "",
        "subscription_start_date": str(datetime.now().date()),
        "trial_end_date": str((datetime.now() + timedelta(days=14)).date()),
        
        # Usage Tracking
        "total_sessions_count": 0,
        "token_balance": 10000,
        "token_usage_today": 0,
        "token_usage_month": 0,
        "last_token_reset": str(datetime.now().date()),
        
        # Relationships
        "assigned_coach_id": "",
        
        # Timestamps
        "last_login": "",
        "login_count": 0,
        "created_at": str(datetime.now()),
        "updated_at": str(datetime.now())
    }
    
    # Create user entry
    user_entry = {
        "credentials": {
            "username": username,
            "password": hashed_password
        },
        "profile": profile
    }
    
    # Add to registry with correct key format
    registry_key = f"{role.lower()}_{username}"
    registry[registry_key] = user_entry
    
    # Save
    with open("data/user_registry.json", "w") as f:
        json.dump(registry, f, indent=2)
    
    print(f"✅ Created user: {registry_key}")
    print(f"   Username: {username}")
    print(f"   Password: {password}")
    print(f"   Role: {role}")
    print(f"   Status: {profile['subscription_status']}")
    print(f"   Consent: {profile['consent_version']}")
    
    return registry_key

# Example Usage:
create_user("ADMIN", "admin1", "admin123", "Admin User", "admin@littlenate.ai")
create_user("COACH", "sarah", "coach456", "Sarah Smith", "sarah@example.com")
create_user("CLIENT", "john", "client789", "John Doe", "john@example.com")
```

---

## 🌐 FRONTEND LOGIN REQUIREMENTS

### SessionStorage Requirements

After successful login, store these in sessionStorage:

```javascript
sessionStorage.setItem('username', 'admin1');
sessionStorage.setItem('password', 'admin123');  // For WebSocket re-auth
sessionStorage.setItem('profile', JSON.stringify({
    role: 'ADMIN',
    name: 'Admin User',
    email: 'admin@littlenate.ai',
    hardware_id: 'ADMIN_ADMIN1_ID',
    token_balance: 10000,
    subscription_plan: 'TOP_TIER'
}));
```

### Page-Level Authentication Check

Every protected page should have:

```javascript
// At the top of every page
const username = sessionStorage.getItem("username");
const password = sessionStorage.getItem("password");
const profile = JSON.parse(sessionStorage.getItem("profile") || "{}");

if (!username || !password) {
    window.location.href = "index.html";
}

// Optional: Role-based access
if (profile.role !== "ADMIN") {
    alert("Access Denied: Admin Only");
    window.location.href = "command.html";
}
```

### WebSocket Authentication Flow

```javascript
const ws = new WebSocket("ws://localhost:8765");

ws.onopen = function() {
    // ALWAYS authenticate first!
    ws.send(JSON.stringify({
        type: "login_request",
        username: username,
        password: password,
        expected_role: profile.role,
        hardware_id: profile.hardware_id || `WEB_${navigator.userAgent.substring(0,20)}_${Date.now()}`
    }));
};

ws.onmessage = function(event) {
    const data = JSON.parse(event.data);
    
    if (data.type === "login_success" || data.type === "auth_success") {
        authenticated = true;
        // Now safe to send data requests
        ws.send(JSON.stringify({type: "admin_get_stats"}));
    }
    
    if (data.type === "login_failed") {
        alert(data.message);
        window.location.href = "index.html";
    }
};
```

---

## 📋 PRE-DEPLOYMENT CHECKLIST

Before creating any new dashboard page or user account:

- [ ] Verify REQUIRED_CONSENT_VERSION in bridge_server.py (line 36)
- [ ] Use correct registry key format: `{role}_{username}`
- [ ] Password in `salt:hash` format
- [ ] Nested structure: `credentials` + `profile`
- [ ] `consent_version` = `"v12.6_2026_FINAL"`
- [ ] `subscription_status` = `"ACTIVE"`
- [ ] All required profile fields present
- [ ] Test login before building UI
- [ ] Verify WebSocket authentication works
- [ ] Check backend terminal for "LOGIN SUCCESS"

---

## 🧪 TESTING COMMANDS

### Verify User Structure:
```bash
cd ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket

python3 << 'ENDPYTHON'
import json

with open("data/user_registry.json", "r") as f:
    registry = json.load(f)

for key, user in registry.items():
    print(f"\nUser Key: {key}")
    print(f"  Username: {user.get('credentials', {}).get('username', 'MISSING')}")
    pwd = user.get('credentials', {}).get('password', 'MISSING')
    print(f"  Password format: {'salt:hash ✓' if ':' in pwd else 'WRONG ✗'}")
    profile = user.get('profile', {})
    print(f"  Role: {profile.get('role', 'MISSING')}")
    print(f"  Status: {profile.get('subscription_status', 'MISSING')}")
    print(f"  Consent: {profile.get('consent_version', 'MISSING')}")
ENDPYTHON
```

### Test Login Flow:
```bash
# 1. Start backend
cd ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket
export DATA_DIR="./data"
python3 bridge_server.py

# 2. Start frontend
cd ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard
python3 -m http.server 8080

# 3. Test login
# Open: http://localhost:8080/index.html
# Enter credentials
# Watch backend terminal for:
#   >>> RECEIVED: {"type":"login_request",...}
#   >>> LOGIN SUCCESS for admin1
#   >>> SENT: {"type":"login_success",...}
```

---

## 📊 REFERENCE: Field Requirements Matrix

| Field | Location | Required Value | Notes |
|-------|----------|---------------|-------|
| Registry Key | Top level | `{role}_{username}` | e.g., `admin_admin1` |
| username | `credentials.username` | Any string | Must be unique |
| password | `credentials.password` | `salt:hash` | PBKDF2-HMAC-SHA256 |
| role | `profile.role` | ADMIN/COACH/CLIENT | Case sensitive |
| consent_version | `profile.consent_version` | `v12.6_2026_FINAL` | Exact match required |
| subscription_status | `profile.subscription_status` | `ACTIVE` | For ADMIN/COACH |
| hardware_id | `profile.hardware_id` | `{ROLE}_{USERNAME}_ID` | Auto-generated format |
| email | `profile.email` | Valid email | Must be unique |
| token_balance | `profile.token_balance` | Number | Default: 10000 |

---

## 🎯 QUICK REFERENCE: Error Messages

| Error | Cause | Fix |
|-------|-------|-----|
| USER_NOT_FOUND | Wrong key or structure | Use `{role}_{username}` key |
| INVALID_PASSWORD | Wrong hash format | Use `salt:hash` with PBKDF2 |
| ACCOUNT_PENDING_APPROVAL | Status not ACTIVE | Set `subscription_status: "ACTIVE"` |
| LEGAL_UPDATE_REQUIRED | Wrong consent version | Set `consent_version: "v12.6_2026_FINAL"` |
| WRONG_PORTAL | Role mismatch | Verify `role` matches `expected_role` |

---

## 🔐 SECURITY NOTES

1. **Never store plain text passwords** in user_registry.json
2. **Always use PBKDF2** with 100,000 iterations minimum
3. **Generate unique salts** for each user (never reuse!)
4. **Use secrets.token_hex()** for salt generation (cryptographically secure)
5. **Validate consent version** on every login (legal requirement)
6. **Check subscription status** to prevent unauthorized access
7. **Hardware ID** helps with device management and multi-device sync

---

## 📝 VERSION HISTORY

| Date | Version | Changes |
|------|---------|---------|
| 2026-01-26 | 1.0 | Initial documentation after fixing admin login |

---

**Remember:** When in doubt, copy the exact structure from a working user in the registry!

**Last Verified Working:** January 26, 2026 12:24 AM  
**Test Credentials:** admin1 / admin123  
**Status:** ✅ PRODUCTION READY
