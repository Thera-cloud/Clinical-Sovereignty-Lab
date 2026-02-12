#!/usr/bin/env python3
"""
LITTLE NATE — Database Migration Script
Version: 1.0
Date: January 21, 2026

Migrates data from user_registry.json to PostgreSQL database.

Usage:
    python migrate_to_postgres.py --dry-run    # Preview changes
    python migrate_to_postgres.py              # Execute migration
"""

import asyncio
import asyncpg
import json
import argparse
import os
from pathlib import Path
from datetime import datetime
import hashlib
import secrets

# =============================================================================
# CONFIGURATION
# =============================================================================

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/little_nate")
REGISTRY_FILE = Path(__file__).parent / "user_registry.json"
VAULT_ROOT = Path(__file__).parent / "Vaults"

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def hash_password(password: str) -> str:
    """Hash password using PBKDF2 (same as api_server.py)"""
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return f"{salt}${hashed.hex()}"

def parse_datetime(dt_string: str) -> datetime:
    """Parse various datetime formats"""
    if not dt_string:
        return None
    
    formats = [
        '%Y-%m-%d %H:%M:%S.%f',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d',
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(dt_string, fmt)
        except ValueError:
            continue
    
    return None

# =============================================================================
# MIGRATION FUNCTIONS
# =============================================================================

async def migrate_users(conn: asyncpg.Connection, registry: dict, dry_run: bool = False):
    """Migrate users from registry to database"""
    
    print("\n📦 Migrating Users...")
    print("-" * 50)
    
    # First pass: Create families
    families_created = set()
    for key, val in registry.items():
        family_id = val.get('profile', {}).get('family_id')
        if family_id and family_id not in families_created:
            if dry_run:
                print(f"  [DRY RUN] Would create family: {family_id}")
            else:
                try:
                    await conn.execute("""
                        INSERT INTO families (family_code)
                        VALUES ($1)
                        ON CONFLICT (family_code) DO NOTHING
                    """, family_id)
                    print(f"  ✅ Created family: {family_id}")
                except Exception as e:
                    print(f"  ⚠️ Family {family_id}: {e}")
            families_created.add(family_id)
    
    # Second pass: Create users
    user_map = {}  # username -> uuid (for guardian linking)
    
    for key, val in registry.items():
        creds = val.get('credentials', {})
        profile = val.get('profile', {})
        
        username = creds.get('username', '')
        password = creds.get('password', '')
        
        if not username:
            print(f"  ⚠️ Skipping entry with no username: {key}")
            continue
        
        # Get family UUID
        family_uuid = None
        family_code = profile.get('family_id')
        if family_code and not dry_run:
            family_uuid = await conn.fetchval(
                "SELECT id FROM families WHERE family_code = $1",
                family_code
            )
        
        user_data = {
            'username': username,
            'password_hash': hash_password(password),
            'name': profile.get('name', username),
            'role': profile.get('role', 'CLIENT'),
            'tier': profile.get('tier', 'STANDARD'),
            'dob': parse_datetime(profile.get('dob')),
            'family_id': family_uuid,
            'hardware_id': profile.get('hardware_id'),
            'consent_version': profile.get('consent_version'),
            'consent_date': parse_datetime(profile.get('consent_date')),
            'consent_proxy': profile.get('consent_proxy'),
            'subscription_status': profile.get('subscription_status', 'TRIAL_ACTIVE'),
            'is_minor': profile.get('is_minor', False),
            'intake_data': json.dumps(profile.get('intake_data', {"goals": [], "modality": "General"}))
        }
        
        if dry_run:
            print(f"  [DRY RUN] Would create user: {username} ({user_data['role']})")
        else:
            try:
                user_uuid = await conn.fetchval("""
                    INSERT INTO users (
                        username, password_hash, name, role, tier,
                        dob, family_id, hardware_id,
                        consent_version, consent_date, consent_proxy,
                        subscription_status, is_minor, intake_data
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                    ON CONFLICT (username) DO UPDATE SET
                        name = EXCLUDED.name,
                        role = EXCLUDED.role,
                        tier = EXCLUDED.tier
                    RETURNING id
                """,
                    user_data['username'],
                    user_data['password_hash'],
                    user_data['name'],
                    user_data['role'],
                    user_data['tier'],
                    user_data['dob'].date() if user_data['dob'] else None,
                    user_data['family_id'],
                    user_data['hardware_id'],
                    user_data['consent_version'],
                    user_data['consent_date'],
                    user_data['consent_proxy'],
                    user_data['subscription_status'],
                    user_data['is_minor'],
                    user_data['intake_data']
                )
                user_map[username] = user_uuid
                print(f"  ✅ Created user: {username} ({user_data['role']}) -> {user_uuid}")
            except Exception as e:
                print(f"  ❌ Failed to create {username}: {e}")
    
    # Third pass: Link guardians
    print("\n🔗 Linking guardians...")
    for key, val in registry.items():
        profile = val.get('profile', {})
        guardian_username = profile.get('guardian_id')
        
        if guardian_username:
            username = val.get('credentials', {}).get('username')
            
            if dry_run:
                print(f"  [DRY RUN] Would link {username} -> guardian {guardian_username}")
            else:
                try:
                    guardian_uuid = user_map.get(guardian_username)
                    user_uuid = user_map.get(username)
                    
                    if guardian_uuid and user_uuid:
                        await conn.execute("""
                            UPDATE users SET guardian_id = $1 WHERE id = $2
                        """, guardian_uuid, user_uuid)
                        print(f"  ✅ Linked {username} -> guardian {guardian_username}")
                except Exception as e:
                    print(f"  ⚠️ Failed to link guardian: {e}")
    
    return user_map

async def migrate_memory_ledgers(conn: asyncpg.Connection, user_map: dict, dry_run: bool = False):
    """Migrate memory ledgers from Vault files"""
    
    print("\n🧠 Migrating Memory Ledgers...")
    print("-" * 50)
    
    clients_dir = VAULT_ROOT / "Clients"
    if not clients_dir.exists():
        print("  ⚠️ No Clients vault directory found")
        return
    
    for user_dir in clients_dir.iterdir():
        if not user_dir.is_dir():
            continue
        
        ledger_file = user_dir / "memory_ledger.txt"
        if not ledger_file.exists():
            continue
        
        # Find user by hardware_id (folder name)
        hardware_id = user_dir.name
        user_uuid = None
        
        for username, uuid in user_map.items():
            # Look up hardware_id in database
            if not dry_run:
                found = await conn.fetchval(
                    "SELECT id FROM users WHERE hardware_id = $1",
                    hardware_id
                )
                if found:
                    user_uuid = found
                    break
        
        if not user_uuid and not dry_run:
            print(f"  ⚠️ No user found for hardware_id: {hardware_id}")
            continue
        
        # Parse and migrate entries
        try:
            with open(ledger_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            entry_count = 0
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Parse format: [timestamp] [Coh:XX.X] ROLE: content
                role = 'USER'
                if 'NATE:' in line:
                    role = 'NATE'
                elif 'SYSTEM:' in line:
                    role = 'SYSTEM'
                
                if dry_run:
                    entry_count += 1
                else:
                    try:
                        await conn.execute("""
                            INSERT INTO memory_ledger (user_id, role, content)
                            VALUES ($1, $2, $3)
                        """, user_uuid, role, line)
                        entry_count += 1
                    except Exception as e:
                        pass  # Skip individual failures
            
            if dry_run:
                print(f"  [DRY RUN] Would migrate {entry_count} entries for {hardware_id}")
            else:
                print(f"  ✅ Migrated {entry_count} memory entries for {hardware_id}")
                
        except Exception as e:
            print(f"  ❌ Failed to migrate ledger for {hardware_id}: {e}")

async def migrate_coach_data(conn: asyncpg.Connection, user_map: dict, dry_run: bool = False):
    """Migrate coach schedules and notes"""
    
    print("\n👩‍⚕️ Migrating Coach Data...")
    print("-" * 50)
    
    coaches_dir = VAULT_ROOT / "Coaches"
    if not coaches_dir.exists():
        print("  ⚠️ No Coaches vault directory found")
        return
    
    for coach_dir in coaches_dir.iterdir():
        if not coach_dir.is_dir():
            continue
        
        hardware_id = coach_dir.name
        
        # Find coach user
        coach_uuid = None
        if not dry_run:
            coach_uuid = await conn.fetchval(
                "SELECT id FROM users WHERE hardware_id = $1",
                hardware_id
            )
        
        # Migrate schedule
        schedule_file = coach_dir / "schedule.json"
        if schedule_file.exists():
            try:
                with open(schedule_file, 'r') as f:
                    schedule = json.load(f)
                
                if dry_run:
                    print(f"  [DRY RUN] Would migrate {len(schedule)} schedule entries for {hardware_id}")
                else:
                    print(f"  ✅ Found {len(schedule)} schedule entries for {hardware_id}")
                    # TODO: Map to sessions table when format is defined
            except Exception as e:
                print(f"  ⚠️ Failed to read schedule for {hardware_id}: {e}")
        
        # Migrate training notes
        for training_dir in coach_dir.iterdir():
            if training_dir.is_dir() and training_dir.name.endswith("_LN_training_folder"):
                note_count = 0
                for note_file in training_dir.glob("*.txt"):
                    if dry_run:
                        note_count += 1
                    else:
                        try:
                            with open(note_file, 'r', encoding='utf-8') as f:
                                content = f.read()
                            
                            # Add to wisdom entries (already processed)
                            await conn.execute("""
                                INSERT INTO wisdom_entries (version, category, source, source_file, content, approved)
                                VALUES ('legacy', 'coach_notes', 'migration', $1, $2, TRUE)
                            """, note_file.name, content)
                            note_count += 1
                        except Exception as e:
                            pass
                
                if note_count > 0:
                    if dry_run:
                        print(f"  [DRY RUN] Would migrate {note_count} training notes for {hardware_id}")
                    else:
                        print(f"  ✅ Migrated {note_count} training notes for {hardware_id}")

async def migrate_wisdom(conn: asyncpg.Connection, dry_run: bool = False):
    """Migrate Night School wisdom"""
    
    print("\n📚 Migrating Wisdom...")
    print("-" * 50)
    
    wisdom_file = VAULT_ROOT / "Admin" / "little_nate_wisdom.json"
    if not wisdom_file.exists():
        print("  ⚠️ No wisdom file found")
        return
    
    try:
        with open(wisdom_file, 'r') as f:
            wisdom_data = json.load(f)
        
        accumulated = wisdom_data.get('accumulated_learnings', '')
        
        if dry_run:
            lines = [l.strip() for l in accumulated.split('\n') if l.strip().startswith('-')]
            print(f"  [DRY RUN] Would migrate {len(lines)} wisdom entries")
        else:
            # Parse individual learnings
            entries = [l.strip()[2:] for l in accumulated.split('\n') if l.strip().startswith('-')]
            
            for entry in entries:
                await conn.execute("""
                    INSERT INTO wisdom_entries (version, category, source, content, approved, is_current)
                    VALUES ('v16.0', 'general', 'night_school', $1, TRUE, TRUE)
                """, entry)
            
            print(f"  ✅ Migrated {len(entries)} wisdom entries")
            
    except Exception as e:
        print(f"  ❌ Failed to migrate wisdom: {e}")

async def create_initial_audit_entry(conn: asyncpg.Connection, dry_run: bool = False):
    """Create audit log entry for migration"""
    
    if dry_run:
        print("\n📋 [DRY RUN] Would create migration audit entry")
        return
    
    await conn.execute("""
        INSERT INTO audit_log (action_type, description)
        VALUES ('CREATE', 'Database migration from user_registry.json completed')
    """)
    print("\n📋 Created migration audit entry")

# =============================================================================
# MAIN
# =============================================================================

async def main(dry_run: bool = False):
    """Run full migration"""
    
    print("=" * 60)
    print("LITTLE NATE — Database Migration")
    print("=" * 60)
    print(f"Mode: {'DRY RUN (no changes)' if dry_run else 'LIVE MIGRATION'}")
    print(f"Source: {REGISTRY_FILE}")
    print(f"Target: {DATABASE_URL}")
    print("=" * 60)
    
    # Load registry
    if not REGISTRY_FILE.exists():
        print(f"\n❌ Registry file not found: {REGISTRY_FILE}")
        return
    
    with open(REGISTRY_FILE, 'r') as f:
        registry = json.load(f)
    
    print(f"\n📂 Found {len(registry)} users in registry")
    
    if dry_run:
        # Just show what would happen
        user_map = await migrate_users(None, registry, dry_run=True)
        await migrate_memory_ledgers(None, {}, dry_run=True)
        await migrate_coach_data(None, {}, dry_run=True)
        await migrate_wisdom(None, dry_run=True)
        
        print("\n" + "=" * 60)
        print("DRY RUN COMPLETE — No changes made")
        print("Run without --dry-run to execute migration")
        print("=" * 60)
        return
    
    # Connect to database
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        print(f"\n✅ Connected to database")
    except Exception as e:
        print(f"\n❌ Database connection failed: {e}")
        print("\nMake sure PostgreSQL is running and the database exists:")
        print("  createdb little_nate")
        print("  psql little_nate < database_schema.sql")
        return
    
    try:
        # Run migrations in transaction
        async with conn.transaction():
            user_map = await migrate_users(conn, registry)
            await migrate_memory_ledgers(conn, user_map)
            await migrate_coach_data(conn, user_map)
            await migrate_wisdom(conn)
            await create_initial_audit_entry(conn)
        
        print("\n" + "=" * 60)
        print("✅ MIGRATION COMPLETE")
        print("=" * 60)
        
        # Print summary
        user_count = await conn.fetchval("SELECT COUNT(*) FROM users")
        family_count = await conn.fetchval("SELECT COUNT(*) FROM families")
        memory_count = await conn.fetchval("SELECT COUNT(*) FROM memory_ledger")
        wisdom_count = await conn.fetchval("SELECT COUNT(*) FROM wisdom_entries")
        
        print(f"\nDatabase Summary:")
        print(f"  Users: {user_count}")
        print(f"  Families: {family_count}")
        print(f"  Memory entries: {memory_count}")
        print(f"  Wisdom entries: {wisdom_count}")
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        print("Transaction rolled back - no changes made")
        raise
    
    finally:
        await conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate Little Nate to PostgreSQL")
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview migration without making changes'
    )
    args = parser.parse_args()
    
    asyncio.run(main(dry_run=args.dry_run))
