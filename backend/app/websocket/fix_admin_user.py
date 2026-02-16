import json
import hashlib
import secrets
import os
import shutil
import datetime as datetime_module
from datetime import datetime, timedelta

# Load existing registry
try:
    with open("data/user_registry.json", "r") as f:
        registry = json.load(f)
except Exception:
    registry = {}

# Create password hash EXACTLY like hash_password() does
password = os.environ.get("ADMIN_PASSWORD")
if not password:
    print("ERROR: ADMIN_PASSWORD env var is required. Exiting.")
    import sys; sys.exit(1)
salt = secrets.token_hex(16)
hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
hashed_password = f"{salt}:{hashed.hex()}"

# Create admin user with EXACT structure
new_profile = {
    "role": "ADMIN",
    "name": "Admin User",
    "email": "admin@littlenate.ai",
    "phone": "",
    "hardware_id": "ADMIN_ADMIN1_ID",
    "family_id": f"FAM_{secrets.token_hex(4).upper()}",
    "joined_date": str(datetime.now().date()),
    "tier": "STANDARD",
    "dob": "",
    "consent_version": "v1.0",
    "timezone": "America/New_York",
    "profile_photo_url": "",
    "emergency_contact": "",
    "subscription_status": "PENDING_VERIFICATION",
    "subscription_plan": "TRIAL",
    "stripe_customer_id": "",
    "subscription_start_date": str(datetime.now().date()),
    "trial_end_date": str((datetime.now() + timedelta(days=14)).date()),
    "total_sessions_count": 0,
    "token_balance": 10000,
    "token_usage_today": 0,
    "token_usage_month": 0,
    "last_token_reset": str(datetime.now().date()),
    "assigned_coach_id": "",
    "last_login": "",
    "login_count": 0,
    "created_at": str(datetime.now()),
    "updated_at": str(datetime.now())
}

admin_user = {
    "credentials": {"username": "admin1", "password": hashed_password},
    "profile": new_profile
}

keys_to_remove = [k for k in list(registry.keys()) if "admin" in k.lower()]
for key in keys_to_remove:
    print(f"Removing: {key}")
    del registry[key]

registry["admin_admin1"] = admin_user

# Backup before destructive write (only if file exists)
if os.path.exists("data/user_registry.json"):
    backup_path = f"data/user_registry.json.bak.{datetime_module.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2("data/user_registry.json", backup_path)
    print(f"Backup created: {backup_path}")

with open("data/user_registry.json", "w") as f:
    json.dump(registry, f, indent=2)

print(f"\n✅ Created: admin_admin1")
print(f"   Username: admin1")
print(f"   Password: [set via ADMIN_PASSWORD env var]")
