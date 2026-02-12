#!/usr/bin/env python3
"""
NIGHT SCHOOL CURRICULUM PATCH
Adds the complete curriculum system to bridge_server.py

Run from your websocket directory:
    python patch_curriculum.py
"""

import os
import shutil
from datetime import datetime
from pathlib import Path

BRIDGE_FILE = "bridge_server.py"

# =============================================================================
# CONTENT TO INSERT
# =============================================================================

IMPORT_LINE = "from night_school_curriculum import NightSchoolCurriculum"

INIT_LINE = "night_school_curriculum = NightSchoolCurriculum(VAULT_ROOT)"

HANDLERS_BLOCK = '''
            # =================================================================
            # NIGHT SCHOOL CURRICULUM HANDLERS
            # =================================================================
            
            # === GET CURRICULUM STRUCTURE ===
            elif t == "get_curriculum_structure":
                if current_profile and current_profile.get("role") == "ADMIN":
                    structure = night_school_curriculum.get_folder_structure()
                    await websocket.send(json.dumps({
                        "type": "curriculum_structure",
                        "data": structure
                    }))
            
            # === UPLOAD CURRICULUM FILE ===
            elif t == "upload_curriculum_file":
                if current_profile and current_profile.get("role") == "ADMIN":
                    import base64
                    filename = d.get("filename", "upload.txt")
                    content_b64 = d.get("content", "")
                    category = d.get("category", "_inbox")
                    
                    try:
                        content = base64.b64decode(content_b64)
                        result = night_school_curriculum.upload_file(filename, content, category)
                        
                        if result.get("success"):
                            await websocket.send(json.dumps({
                                "type": "file_uploaded",
                                "data": result
                            }))
                        else:
                            await websocket.send(json.dumps({
                                "type": "error",
                                "message": result.get("error", "Upload failed")
                            }))
                    except Exception as e:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": str(e)
                        }))
            
            # === MOVE CURRICULUM FILE ===
            elif t == "move_curriculum_file":
                if current_profile and current_profile.get("role") == "ADMIN":
                    success = night_school_curriculum.move_to_category(
                        d.get("filename"),
                        d.get("from_category"),
                        d.get("to_category")
                    )
                    await websocket.send(json.dumps({
                        "type": "file_moved" if success else "error",
                        "filename": d.get("filename"),
                        "to_category": d.get("to_category"),
                        "message": "" if success else "Move failed"
                    }))
            
            # === DELETE CURRICULUM FILE ===
            elif t == "delete_curriculum_file":
                if current_profile and current_profile.get("role") == "ADMIN":
                    success = night_school_curriculum.delete_file(
                        d.get("filename"),
                        d.get("category")
                    )
                    await websocket.send(json.dumps({
                        "type": "file_deleted" if success else "error",
                        "message": "" if success else "Delete failed"
                    }))
            
            # === RUN CURRICULUM INGESTION ===
            elif t == "run_curriculum_ingestion":
                if current_profile and current_profile.get("role") == "ADMIN":
                    categories = d.get("categories")  # None = all
                    
                    await websocket.send(json.dumps({
                        "type": "ingestion_started"
                    }))
                    
                    try:
                        results = await night_school_curriculum.run_ingestion(categories)
                        await websocket.send(json.dumps({
                            "type": "ingestion_complete",
                            "results": results
                        }))
                    except Exception as e:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": f"Ingestion failed: {str(e)}"
                        }))
            
            # === GET CURRICULUM WISDOM ===
            elif t == "get_curriculum_wisdom":
                if current_profile and current_profile.get("role") in ["ADMIN", "COACH"]:
                    category = d.get("category")
                    if category:
                        wisdom = night_school_curriculum.get_wisdom_for_category(category)
                    else:
                        wisdom = night_school_curriculum.get_wisdom()
                    
                    await websocket.send(json.dumps({
                        "type": "curriculum_wisdom",
                        "data": wisdom
                    }))
'''


def main():
    print("=" * 60)
    print("NIGHT SCHOOL CURRICULUM PATCH")
    print("=" * 60)
    print()
    
    # Check file exists
    if not os.path.exists(BRIDGE_FILE):
        print(f"❌ Error: {BRIDGE_FILE} not found")
        print("   Run this from your backend/app/websocket directory")
        return False
    
    # Create backup
    backup_name = f"{BRIDGE_FILE}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy(BRIDGE_FILE, backup_name)
    print(f"✅ Backup: {backup_name}")
    
    # Read file
    with open(BRIDGE_FILE, 'r') as f:
        content = f.read()
    
    lines = content.split('\n')
    modified = False
    
    # ==========================================================================
    # STEP 1: Add import
    # ==========================================================================
    if IMPORT_LINE in content:
        print("⏭️  Import already exists")
    else:
        # Find the line with "from bridge_handlers_v2 import"
        for i, line in enumerate(lines):
            if "from bridge_handlers_v2 import" in line:
                lines.insert(i + 1, IMPORT_LINE)
                print("✅ Added import statement")
                modified = True
                break
        else:
            # Fallback: add after pathlib import
            for i, line in enumerate(lines):
                if "from pathlib import Path" in line:
                    lines.insert(i + 1, IMPORT_LINE)
                    print("✅ Added import (fallback location)")
                    modified = True
                    break
    
    # ==========================================================================
    # STEP 2: Add initialization
    # ==========================================================================
    content_check = '\n'.join(lines)
    if INIT_LINE in content_check:
        print("⏭️  Initialization already exists")
    else:
        # Find "night_school = NightSchool(VAULT_ROOT)"
        for i, line in enumerate(lines):
            if "night_school = NightSchool(VAULT_ROOT)" in line:
                lines.insert(i + 1, INIT_LINE)
                print("✅ Added initialization")
                modified = True
                break
        else:
            print("⚠️  Could not find initialization location")
            print(f"   Please add manually after NightSchool init:")
            print(f"   {INIT_LINE}")
    
    # ==========================================================================
    # STEP 3: Add handlers
    # ==========================================================================
    content_check = '\n'.join(lines)
    if 'elif t == "get_curriculum_structure"' in content_check:
        print("⏭️  Handlers already exist")
    else:
        # Find the end of add_coach_learning handler
        # Look for the line after "Content too short" error
        for i, line in enumerate(lines):
            if '"Content too short"' in line:
                # Find the closing of this handler block
                # It's usually 2 lines after (the closing brace and empty line)
                insert_pos = i + 2
                
                # Make sure we're at a good spot (look for next elif or empty line)
                while insert_pos < len(lines) and lines[insert_pos].strip() and not lines[insert_pos].strip().startswith('elif') and not lines[insert_pos].strip().startswith('#'):
                    insert_pos += 1
                
                # Insert handlers
                handler_lines = HANDLERS_BLOCK.split('\n')
                for j, handler_line in enumerate(handler_lines):
                    lines.insert(insert_pos + j, handler_line)
                
                print("✅ Added curriculum handlers")
                modified = True
                break
        else:
            print("⚠️  Could not find handler insertion point")
            print("   Please add handlers manually after 'add_coach_learning' handler")
            # Save handlers to file
            with open("_curriculum_handlers.txt", 'w') as f:
                f.write(HANDLERS_BLOCK)
            print("   Handlers saved to: _curriculum_handlers.txt")
    
    # ==========================================================================
    # STEP 4: Save
    # ==========================================================================
    if modified:
        with open(BRIDGE_FILE, 'w') as f:
            f.write('\n'.join(lines))
        print("✅ Saved bridge_server.py")
    
    print()
    print("=" * 60)
    print("✅ PATCH COMPLETE")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Copy night_school_curriculum.py to this directory")
    print("  2. Install optional deps: pip3 install PyPDF2 python-docx")
    print("  3. Restart server: python3 bridge_server.py")
    print()
    
    return True


if __name__ == "__main__":
    main()
