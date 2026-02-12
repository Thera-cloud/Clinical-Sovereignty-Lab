#!/usr/bin/env python3
"""
NIGHT SCHOOL HANDLERS PATCH FOR BRIDGE_SERVER.PY
Works on macOS, Linux, and Windows

Run from your backend/websocket directory:
    python patch_night_school.py
"""

import os
import sys
import shutil
from datetime import datetime
from pathlib import Path

BRIDGE_FILE = "bridge_server.py"

# ============================================================================
# NIGHT SCHOOL NOTES CLASS
# ============================================================================

NIGHT_SCHOOL_NOTES_CLASS = '''"""
Night School Notes Handler - Coach Notes, Curriculum, and Wisdom Management
"""

import json
import datetime
import base64
import secrets
import hashlib
import re
from pathlib import Path
from typing import Dict, Any, List, Optional


class NightSchoolNotes:
    """Handles coach notes ingestion for Night School."""
    
    def __init__(self, root: Path, night_school):
        self.root = root
        self.night_school = night_school
        self.notes_file = root / "Admin" / "pending_coach_notes.json"
        self.curriculum_folder = root / "Admin" / "admin_LN_training_folder"
        self.curriculum_folder.mkdir(parents=True, exist_ok=True)
    
    def get_pending_notes(self) -> List[Dict[str, Any]]:
        if not self.notes_file.exists():
            return []
        try:
            with open(self.notes_file, 'r') as f:
                return json.load(f)
        except:
            return []
    
    def add_note(self, note: Dict[str, Any]) -> str:
        notes = self.get_pending_notes()
        note_id = f"note_{secrets.token_hex(8)}"
        content = note.get("content", "")
        pii_matches = self._detect_pii(content)
        
        new_note = {
            "id": note_id,
            "coach": note.get("coach", "Unknown Coach"),
            "coach_id": note.get("coach_id", ""),
            "avatar": note.get("avatar", "👨‍⚕️"),
            "session": note.get("session", ""),
            "client_id": note.get("client_id", ""),
            "date": note.get("date", str(datetime.datetime.now())),
            "content": content,
            "category": note.get("category", "general"),
            "tags": note.get("tags", []),
            "status": "flagged" if pii_matches else "pending",
            "has_pii": bool(pii_matches),
            "pii_matches": pii_matches,
            "created_at": str(datetime.datetime.now())
        }
        notes.insert(0, new_note)
        self._save_notes(notes)
        return note_id
    
    def approve_note(self, note_id: str) -> bool:
        notes = self.get_pending_notes()
        for note in notes:
            if note.get("id") == note_id:
                if note.get("has_pii"):
                    return False
                note["status"] = "approved"
                note["approved_at"] = str(datetime.datetime.now())
                self.night_school.add_learning(
                    content=note.get("content", ""),
                    source=f"COACH_NOTE_{note.get('coach_id', 'unknown')}",
                    filename=f"coach_note_{note_id}.txt",
                    category=note.get("category", "general")
                )
                self._save_notes(notes)
                return True
        return False
    
    def reject_note(self, note_id: str, reason: str = "") -> bool:
        notes = self.get_pending_notes()
        for note in notes:
            if note.get("id") == note_id:
                note["status"] = "rejected"
                note["rejected_at"] = str(datetime.datetime.now())
                note["rejection_reason"] = reason
                self._save_notes(notes)
                return True
        return False
    
    def redact_note(self, note_id: str, new_content: str) -> bool:
        notes = self.get_pending_notes()
        for note in notes:
            if note.get("id") == note_id:
                note["content"] = new_content
                note["redacted_at"] = str(datetime.datetime.now())
                pii_matches = self._detect_pii(new_content)
                note["has_pii"] = bool(pii_matches)
                note["pii_matches"] = pii_matches
                note["status"] = "flagged" if pii_matches else "pending"
                self._save_notes(notes)
                return True
        return False
    
    def _detect_pii(self, text: str) -> List[str]:
        pii_found = []
        if re.search(r\'\\b\\d{3}-?\\d{2}-?\\d{4}\\b\', text):
            pii_found.append("SSN")
        if re.search(r\'\\b\\d{3}[-.]?\\d{3}[-.]?\\d{4}\\b\', text):
            pii_found.append("Phone Number")
        emails = re.findall(r\'[\\w\\.-]+@[\\w\\.-]+\\.\\w+\', text)
        pii_found.extend(emails)
        brackets = re.findall(r\'\\[([^\\]]+)\\]\', text)
        for b in brackets:
            if b not in ["REDACTED", "NAME", "COMPANY", "LOCATION"]:
                pii_found.append(b)
        return pii_found
    
    def _save_notes(self, notes: List[Dict]) -> bool:
        try:
            with open(self.notes_file, 'w') as f:
                json.dump(notes, f, indent=2, default=str)
            return True
        except:
            return False
    
    def get_curriculum_files(self) -> List[Dict[str, Any]]:
        files = []
        if not self.curriculum_folder.exists():
            return files
        for file_path in self.curriculum_folder.iterdir():
            if file_path.is_file() and not file_path.name.startswith('.'):
                stat = file_path.stat()
                ext = file_path.suffix.lower()
                file_type = 'txt'
                if ext == '.pdf':
                    file_type = 'pdf'
                elif ext in ['.docx', '.doc']:
                    file_type = 'doc'
                elif ext == '.md':
                    file_type = 'md'
                processed_marker = self.curriculum_folder / f".processed_{file_path.name}"
                status = "ingested" if processed_marker.exists() else "queued"
                files.append({
                    "id": hashlib.md5(file_path.name.encode()).hexdigest()[:16],
                    "name": file_path.name,
                    "size": self._format_size(stat.st_size),
                    "type": file_type,
                    "status": status,
                    "date": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    "category": self._detect_category(file_path.name)
                })
        return sorted(files, key=lambda x: x['date'], reverse=True)
    
    def upload_curriculum(self, filename: str, content_base64: str) -> Dict[str, Any]:
        try:
            content = base64.b64decode(content_base64)
            safe_name = "".join(c for c in filename if c.isalnum() or c in '.-_')
            if not safe_name:
                safe_name = f"upload_{secrets.token_hex(4)}.txt"
            file_path = self.curriculum_folder / safe_name
            counter = 1
            while file_path.exists():
                name, ext = safe_name.rsplit('.', 1) if '.' in safe_name else (safe_name, 'txt')
                file_path = self.curriculum_folder / f"{name}_{counter}.{ext}"
                counter += 1
            with open(file_path, 'wb') as f:
                f.write(content)
            return {
                "success": True,
                "file_id": hashlib.md5(file_path.name.encode()).hexdigest()[:16],
                "filename": file_path.name,
                "size": self._format_size(len(content))
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def delete_curriculum(self, file_id: str) -> bool:
        for file_path in self.curriculum_folder.iterdir():
            if hashlib.md5(file_path.name.encode()).hexdigest()[:16] == file_id:
                try:
                    file_path.unlink()
                    marker = self.curriculum_folder / f".processed_{file_path.name}"
                    if marker.exists():
                        marker.unlink()
                    return True
                except:
                    return False
        return False
    
    def _format_size(self, bytes: int) -> str:
        if bytes < 1024:
            return f"{bytes} B"
        elif bytes < 1024 * 1024:
            return f"{bytes // 1024} KB"
        else:
            return f"{bytes / (1024 * 1024):.1f} MB"
    
    def _detect_category(self, filename: str) -> str:
        lower = filename.lower()
        if 'cbt' in lower or 'cognitive' in lower:
            return 'cbt'
        elif 'crisis' in lower or 'emergency' in lower or 'safety' in lower:
            return 'crisis'
        elif 'family' in lower or 'parent' in lower:
            return 'family'
        elif 'work' in lower or 'job' in lower or 'career' in lower:
            return 'workplace'
        elif 'hipaa' in lower or 'compliance' in lower or 'legal' in lower:
            return 'compliance'
        return 'other'
    
    def save_wisdom(self, wisdom_data: Dict[str, Any]) -> bool:
        wisdom_file = self.root / "Admin" / "little_nate_wisdom.json"
        try:
            if wisdom_file.exists():
                backup = wisdom_file.with_suffix('.json.bak')
                shutil.copy(wisdom_file, backup)
            wisdom_data["last_modified"] = str(datetime.datetime.now())
            wisdom_data["total_entries"] = len(wisdom_data.get("entries", []))
            with open(wisdom_file, 'w') as f:
                json.dump(wisdom_data, f, indent=2, default=str)
            return True
        except Exception as e:
            print(f">>> [ERROR] Failed to save wisdom: {e}")
            return False
    
    def add_wisdom_entry(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        wisdom = self.night_school.get_wisdom_structured()
        if "entries" not in wisdom:
            wisdom["entries"] = []
        if not entry.get("id"):
            max_id = max([e.get("id", 0) for e in wisdom["entries"]] + [0])
            entry["id"] = max_id + 1
        entry["timestamp"] = str(datetime.datetime.now())
        entry["approved"] = True
        wisdom["entries"].insert(0, entry)
        if self.save_wisdom(wisdom):
            return {"success": True, "entry_id": entry["id"]}
        return {"success": False, "error": "Failed to save"}
    
    def update_wisdom_entry(self, entry_id: int, updates: Dict[str, Any]) -> bool:
        wisdom = self.night_school.get_wisdom_structured()
        for entry in wisdom.get("entries", []):
            if entry.get("id") == entry_id:
                for key, value in updates.items():
                    if key not in ["id", "timestamp"]:
                        entry[key] = value
                entry["updated_at"] = str(datetime.datetime.now())
                return self.save_wisdom(wisdom)
        return False
    
    def delete_wisdom_entry(self, entry_id: int) -> bool:
        wisdom = self.night_school.get_wisdom_structured()
        original_len = len(wisdom.get("entries", []))
        wisdom["entries"] = [e for e in wisdom.get("entries", []) if e.get("id") != entry_id]
        if len(wisdom["entries"]) < original_len:
            return self.save_wisdom(wisdom)
        return False
    
    def create_snapshot(self, name: str) -> Dict[str, Any]:
        wisdom = self.night_school.get_wisdom_structured()
        snapshots_dir = self.root / "Admin" / "wisdom_snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c for c in name if c.isalnum() or c in '-_')
        filename = f"{timestamp}_{safe_name}.json"
        snapshot_file = snapshots_dir / filename
        try:
            snapshot_data = {
                "name": name,
                "created_at": str(datetime.datetime.now()),
                "wisdom": wisdom
            }
            with open(snapshot_file, 'w') as f:
                json.dump(snapshot_data, f, indent=2, default=str)
            return {"success": True, "filename": filename}
        except Exception as e:
            return {"success": False, "error": str(e)}
'''

# ============================================================================
# HANDLERS BLOCK
# ============================================================================

HANDLERS_BLOCK = '''
            # =================================================================
            # NIGHT SCHOOL: COACH NOTES HANDLERS
            # =================================================================
            
            # === GET PENDING NOTES ===
            elif t == "get_pending_notes":
                if current_profile and current_profile.get("role") == "ADMIN":
                    notes = night_school_notes.get_pending_notes()
                    await websocket.send(json.dumps({
                        "type": "pending_notes",
                        "notes": notes
                    }))
            
            # === APPROVE NOTE ===
            elif t == "approve_note":
                if current_profile and current_profile.get("role") == "ADMIN":
                    note_id = d.get("note_id", "")
                    success = night_school_notes.approve_note(note_id)
                    await websocket.send(json.dumps({
                        "type": "note_approved" if success else "error",
                        "note_id": note_id,
                        "message": "Note ingested" if success else "Cannot approve note with PII"
                    }))
            
            # === REJECT NOTE ===
            elif t == "reject_note":
                if current_profile and current_profile.get("role") == "ADMIN":
                    note_id = d.get("note_id", "")
                    reason = d.get("reason", "")
                    success = night_school_notes.reject_note(note_id, reason)
                    await websocket.send(json.dumps({
                        "type": "note_rejected" if success else "error",
                        "note_id": note_id
                    }))
            
            # === REDACT NOTE ===
            elif t == "redact_note":
                if current_profile and current_profile.get("role") == "ADMIN":
                    note_id = d.get("note_id", "")
                    content = d.get("content", "")
                    success = night_school_notes.redact_note(note_id, content)
                    await websocket.send(json.dumps({
                        "type": "note_redacted" if success else "error",
                        "note_id": note_id,
                        "content": content
                    }))
            
            # =================================================================
            # NIGHT SCHOOL: CURRICULUM HANDLERS
            # =================================================================
            
            # === GET CURRICULUM FILES ===
            elif t == "get_curriculum_files":
                if current_profile and current_profile.get("role") == "ADMIN":
                    files = night_school_notes.get_curriculum_files()
                    await websocket.send(json.dumps({
                        "type": "curriculum_files",
                        "files": files
                    }))
            
            # === UPLOAD CURRICULUM ===
            elif t == "upload_curriculum":
                if current_profile and current_profile.get("role") == "ADMIN":
                    filename = d.get("filename", "upload.txt")
                    content = d.get("content", "")
                    result = night_school_notes.upload_curriculum(filename, content)
                    if result.get("success"):
                        await websocket.send(json.dumps({
                            "type": "file_uploaded",
                            "file_id": result.get("file_id"),
                            "filename": result.get("filename"),
                            "size": result.get("size")
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": result.get("error", "Upload failed")
                        }))
            
            # === DELETE CURRICULUM ===
            elif t == "delete_curriculum":
                if current_profile and current_profile.get("role") == "ADMIN":
                    file_id = d.get("file_id", "")
                    success = night_school_notes.delete_curriculum(file_id)
                    await websocket.send(json.dumps({
                        "type": "file_deleted" if success else "error",
                        "file_id": file_id
                    }))
            
            # === TRIGGER NIGHT SCHOOL ===
            elif t == "trigger_night_school":
                if current_profile and current_profile.get("role") == "ADMIN":
                    await websocket.send(json.dumps({
                        "type": "night_school_started",
                        "message": "Night School session starting..."
                    }))
                    await night_school.start_session()
                    await websocket.send(json.dumps({
                        "type": "night_school_complete",
                        "message": "Night School session complete"
                    }))
            
            # =================================================================
            # NIGHT SCHOOL: WISDOM HANDLERS
            # =================================================================
            
            # === SAVE WISDOM ===
            elif t == "save_wisdom":
                if current_profile and current_profile.get("role") == "ADMIN":
                    wisdom_data = d.get("wisdom", {})
                    success = night_school_notes.save_wisdom(wisdom_data)
                    await websocket.send(json.dumps({
                        "type": "wisdom_saved" if success else "error",
                        "message": "Wisdom saved" if success else "Failed to save"
                    }))
            
            # === ADD WISDOM ENTRY ===
            elif t == "add_wisdom_entry":
                if current_profile and current_profile.get("role") == "ADMIN":
                    entry = d.get("entry", {})
                    result = night_school_notes.add_wisdom_entry(entry)
                    await websocket.send(json.dumps({
                        "type": "wisdom_entry_added" if result.get("success") else "error",
                        "entry_id": result.get("entry_id"),
                        "message": result.get("error", "")
                    }))
            
            # === UPDATE WISDOM ENTRY ===
            elif t == "update_wisdom_entry":
                if current_profile and current_profile.get("role") == "ADMIN":
                    entry_id = d.get("entry_id")
                    content = d.get("content", "")
                    confidence = d.get("confidence", 0.85)
                    success = night_school_notes.update_wisdom_entry(entry_id, {
                        "content": content,
                        "confidence": confidence
                    })
                    await websocket.send(json.dumps({
                        "type": "wisdom_entry_updated" if success else "error",
                        "entry_id": entry_id
                    }))
            
            # === DELETE WISDOM ENTRY ===
            elif t == "delete_wisdom_entry":
                if current_profile and current_profile.get("role") == "ADMIN":
                    entry_id = d.get("entry_id")
                    success = night_school_notes.delete_wisdom_entry(entry_id)
                    await websocket.send(json.dumps({
                        "type": "wisdom_entry_deleted" if success else "error",
                        "entry_id": entry_id
                    }))
            
            # === CREATE WISDOM SNAPSHOT ===
            elif t == "create_wisdom_snapshot":
                if current_profile and current_profile.get("role") == "ADMIN":
                    name = d.get("name", "manual_snapshot")
                    result = night_school_notes.create_snapshot(name)
                    await websocket.send(json.dumps({
                        "type": "snapshot_created" if result.get("success") else "error",
                        "name": name,
                        "filename": result.get("filename", ""),
                        "message": result.get("error", "")
                    }))
'''

def main():
    print("=" * 60)
    print("NIGHT SCHOOL HANDLERS PATCH")
    print("=" * 60)
    print()
    
    # Check if bridge_server.py exists
    if not os.path.exists(BRIDGE_FILE):
        print(f"❌ Error: {BRIDGE_FILE} not found in current directory")
        print("   Run this script from your backend/websocket directory")
        sys.exit(1)
    
    # Create backup
    backup_name = f"{BRIDGE_FILE}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy(BRIDGE_FILE, backup_name)
    print(f"✅ Backup created: {backup_name}")
    
    # Create night_school_notes.py
    with open("night_school_notes.py", "w") as f:
        f.write(NIGHT_SCHOOL_NOTES_CLASS)
    print("✅ Created night_school_notes.py")
    
    # Read bridge_server.py
    with open(BRIDGE_FILE, "r") as f:
        content = f.read()
    
    # Add import statement
    import_line = "from night_school_notes import NightSchoolNotes"
    if import_line not in content:
        # Find the line with bridge_handlers_v2 import
        target = "from bridge_handlers_v2 import CoachNexusV2"
        if target in content:
            content = content.replace(target, f"{target}\n{import_line}")
            print("✅ Added import statement")
        else:
            print("⚠️  Could not find import location, please add manually:")
            print(f"   {import_line}")
    else:
        print("⏭️  Import already exists, skipping")
    
    # Add initialization
    init_line = "night_school_notes = NightSchoolNotes(VAULT_ROOT, night_school)"
    if init_line not in content:
        target = "night_school = NightSchool(VAULT_ROOT)"
        if target in content:
            content = content.replace(target, f"{target}\n{init_line}")
            print("✅ Added initialization")
        else:
            print("⚠️  Could not find initialization location, please add manually:")
            print(f"   {init_line}")
    else:
        print("⏭️  Initialization already exists, skipping")
    
    # Check if handlers already exist
    if 'elif t == "get_pending_notes"' in content:
        print("⏭️  Handlers already exist, skipping")
    else:
        # Save handlers to file for manual insertion
        with open("_night_school_handlers.txt", "w") as f:
            f.write(HANDLERS_BLOCK)
        print("✅ Created _night_school_handlers.txt")
        print()
        print("⚠️  MANUAL STEP REQUIRED:")
        print("   1. Open bridge_server.py in Cursor")
        print('   2. Find: elif t == "add_coach_learning"')
        print("   3. After that handler block ends (~15 lines later)")
        print("   4. Paste contents of: _night_school_handlers.txt")
    
    # Save modified bridge_server.py
    with open(BRIDGE_FILE, "w") as f:
        f.write(content)
    print("✅ Saved bridge_server.py")
    
    print()
    print("=" * 60)
    print("✅ PATCH COMPLETE")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Add handlers from _night_school_handlers.txt (if needed)")
    print("  2. Save bridge_server.py")
    print("  3. Restart: python bridge_server.py")
    print()

if __name__ == "__main__":
    main()
