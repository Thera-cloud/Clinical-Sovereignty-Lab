"""
NIGHT SCHOOL CURRICULUM SYSTEM
Enhanced learning engine with categorized folder structure and file processing

Folder Structure:
/Admin/
├── little_nate_wisdom.json          # Synthesized knowledge base
├── learning_history.json            # All ingested learnings
├── admin_LN_training_folder/
│   ├── _inbox/                      # New uploads land here
│   ├── cbt/                         # Cognitive Behavioral Therapy
│   ├── crisis/                      # Crisis intervention & safety
│   ├── family/                      # Family systems & relationships
│   ├── workplace/                   # Career & workplace issues
│   ├── compliance/                  # HIPAA, ethics, legal
│   ├── attachment/                  # Attachment theory
│   ├── trauma/                      # Trauma-informed care
│   ├── mindfulness/                 # Mindfulness & grounding
│   ├── communication/               # Communication skills
│   └── general/                     # Uncategorized

Usage:
1. Import this class in bridge_server.py
2. Replace or extend existing NightSchool class
3. Upload files via curriculum page → lands in _inbox
4. Admin reviews and assigns category
5. Run Night School to ingest into wisdom
"""

import json
import datetime
import hashlib
import secrets
import re
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

# Optional imports for file parsing
try:
    import PyPDF2
    HAS_PDF = True
except ImportError:
    HAS_PDF = False
    print("[!] PyPDF2 not installed - PDF parsing disabled. Run: pip install PyPDF2")

try:
    from docx import Document
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False
    print("[!] python-docx not installed - DOCX parsing disabled. Run: pip install python-docx")


# =============================================================================
# CATEGORY DEFINITIONS
# =============================================================================

CATEGORIES = {
    "cbt": {
        "name": "Cognitive Behavioral Therapy",
        "description": "CBT techniques, thought restructuring, behavioral activation",
        "keywords": ["cbt", "cognitive", "behavioral", "thought", "belief", "distortion", "reframe"]
    },
    "crisis": {
        "name": "Crisis Intervention",
        "description": "Safety protocols, suicide prevention, crisis de-escalation",
        "keywords": ["crisis", "suicide", "safety", "emergency", "988", "hotline", "harm", "danger"]
    },
    "family": {
        "name": "Family Systems",
        "description": "Family dynamics, parenting, relationship patterns",
        "keywords": ["family", "parent", "child", "spouse", "marriage", "divorce", "sibling"]
    },
    "workplace": {
        "name": "Workplace & Career",
        "description": "Work stress, career issues, professional boundaries",
        "keywords": ["work", "job", "career", "boss", "colleague", "burnout", "professional"]
    },
    "compliance": {
        "name": "Compliance & Ethics",
        "description": "HIPAA, confidentiality, ethical guidelines, legal requirements",
        "keywords": ["hipaa", "compliance", "ethics", "legal", "confidential", "consent", "boundary"]
    },
    "attachment": {
        "name": "Attachment Theory",
        "description": "Attachment styles, relationship patterns, early bonds",
        "keywords": ["attachment", "secure", "anxious", "avoidant", "bond", "connection"]
    },
    "trauma": {
        "name": "Trauma-Informed Care",
        "description": "Trauma processing, PTSD, somatic approaches",
        "keywords": ["trauma", "ptsd", "somatic", "trigger", "flashback", "abuse", "neglect"]
    },
    "mindfulness": {
        "name": "Mindfulness & Grounding",
        "description": "Present-moment awareness, grounding techniques, relaxation",
        "keywords": ["mindful", "grounding", "breathe", "meditation", "present", "calm", "relax"]
    },
    "communication": {
        "name": "Communication Skills",
        "description": "Active listening, assertiveness, conflict resolution",
        "keywords": ["communication", "listen", "assertive", "conflict", "boundary", "express"]
    },
    "general": {
        "name": "General Therapeutic Knowledge",
        "description": "Uncategorized therapeutic content",
        "keywords": []
    }
}


# =============================================================================
# ENHANCED NIGHT SCHOOL CLASS
# =============================================================================

class NightSchoolCurriculum:
    """
    Enhanced Night School system with categorized folder structure.
    """
    
    def __init__(self, root: Path):
        self.root = root
        self.admin_dir = root / "Admin"
        self.curriculum_dir = self.admin_dir / "admin_LN_training_folder"
        self.wisdom_file = self.admin_dir / "little_nate_wisdom.json"
        self.learnings_file = self.admin_dir / "learning_history.json"
        
        # Initialize folder structure
        self._init_folders()
    
    def _init_folders(self):
        """Create category folder structure."""
        self.admin_dir.mkdir(parents=True, exist_ok=True)
        self.curriculum_dir.mkdir(parents=True, exist_ok=True)
        
        # Create inbox for new uploads
        (self.curriculum_dir / "_inbox").mkdir(exist_ok=True)
        
        # Create category folders
        for category in CATEGORIES.keys():
            (self.curriculum_dir / category).mkdir(exist_ok=True)
        
        print(f"[*] Night School folders initialized at {self.curriculum_dir}")
    
    # -------------------------------------------------------------------------
    # FILE OPERATIONS
    # -------------------------------------------------------------------------
    
    def get_folder_structure(self) -> Dict[str, Any]:
        """Get current folder structure with file counts."""
        structure = {"_inbox": [], "categories": {}}
        
        # Get inbox files
        inbox = self.curriculum_dir / "_inbox"
        if inbox.exists():
            for f in inbox.iterdir():
                if f.is_file() and not f.name.startswith('.'):
                    structure["_inbox"].append(self._file_info(f))
        
        # Get category folders
        for cat_id, cat_info in CATEGORIES.items():
            cat_dir = self.curriculum_dir / cat_id
            files = []
            if cat_dir.exists():
                for f in cat_dir.iterdir():
                    if f.is_file() and not f.name.startswith('.'):
                        files.append(self._file_info(f))
            
            structure["categories"][cat_id] = {
                "name": cat_info["name"],
                "description": cat_info["description"],
                "file_count": len(files),
                "files": files
            }
        
        return structure
    
    def _file_info(self, path: Path) -> Dict[str, Any]:
        """Get file metadata."""
        stat = path.stat()
        return {
            "id": hashlib.md5(path.name.encode()).hexdigest()[:16],
            "name": path.name,
            "size": self._format_size(stat.st_size),
            "size_bytes": stat.st_size,
            "type": path.suffix.lower().replace('.', ''),
            "modified": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "path": str(path.relative_to(self.curriculum_dir)),
            "ingested": (path.parent / f".ingested_{path.name}").exists()
        }
    
    def upload_file(self, filename: str, content: bytes, category: str = "_inbox") -> Dict[str, Any]:
        """
        Upload a file to the curriculum folder.
        
        Args:
            filename: Original filename
            content: File bytes (not base64)
            category: Target category folder (default: _inbox)
        
        Returns:
            Result dict with success status and file info
        """
        try:
            # Sanitize filename
            safe_name = self._sanitize_filename(filename)
            
            # Determine target folder
            if category == "_inbox" or category not in CATEGORIES:
                target_dir = self.curriculum_dir / "_inbox"
            else:
                target_dir = self.curriculum_dir / category
            
            target_dir.mkdir(exist_ok=True)
            
            # Handle duplicates
            file_path = target_dir / safe_name
            counter = 1
            while file_path.exists():
                stem = Path(safe_name).stem
                suffix = Path(safe_name).suffix
                file_path = target_dir / f"{stem}_{counter}{suffix}"
                counter += 1
            
            # Write file
            with open(file_path, 'wb') as f:
                f.write(content)
            
            return {
                "success": True,
                "file": self._file_info(file_path),
                "category": category,
                "auto_category": self._detect_category(safe_name, content)
            }
        
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def move_to_category(self, filename: str, from_category: str, to_category: str) -> bool:
        """Move a file from one category to another."""
        try:
            if from_category == "_inbox":
                source = self.curriculum_dir / "_inbox" / filename
            else:
                source = self.curriculum_dir / from_category / filename
            
            if to_category == "_inbox":
                dest_dir = self.curriculum_dir / "_inbox"
            else:
                dest_dir = self.curriculum_dir / to_category
            
            dest_dir.mkdir(exist_ok=True)
            dest = dest_dir / filename
            
            if source.exists():
                shutil.move(str(source), str(dest))
                # Also move ingested marker if exists
                marker = source.parent / f".ingested_{filename}"
                if marker.exists():
                    shutil.move(str(marker), str(dest_dir / f".ingested_{filename}"))
                return True
            return False
        except:
            return False
    
    def delete_file(self, filename: str, category: str) -> bool:
        """Delete a file from curriculum."""
        try:
            if category == "_inbox":
                file_path = self.curriculum_dir / "_inbox" / filename
            else:
                file_path = self.curriculum_dir / category / filename
            
            if file_path.exists():
                file_path.unlink()
                # Remove ingested marker
                marker = file_path.parent / f".ingested_{filename}"
                if marker.exists():
                    marker.unlink()
                return True
            return False
        except:
            return False
    
    def _sanitize_filename(self, filename: str) -> str:
        """Clean filename for safe storage."""
        # Keep only safe characters
        safe = "".join(c for c in filename if c.isalnum() or c in '.-_ ')
        safe = safe.strip()
        if not safe or safe.startswith('.'):
            safe = f"upload_{secrets.token_hex(4)}.txt"
        return safe
    
    def _format_size(self, bytes: int) -> str:
        if bytes < 1024:
            return f"{bytes} B"
        elif bytes < 1024 * 1024:
            return f"{bytes // 1024} KB"
        else:
            return f"{bytes / (1024 * 1024):.1f} MB"
    
    # -------------------------------------------------------------------------
    # CONTENT EXTRACTION
    # -------------------------------------------------------------------------
    
    def extract_content(self, file_path: Path) -> Tuple[str, str]:
        """
        Extract text content from a file.
        
        Returns:
            Tuple of (content, error_message)
        """
        suffix = file_path.suffix.lower()
        
        try:
            if suffix in ['.txt', '.md', '.log']:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read(), ""
            
            elif suffix == '.json':
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Convert JSON to readable text
                    return json.dumps(data, indent=2), ""
            
            elif suffix == '.pdf':
                if not HAS_PDF:
                    return "", "PyPDF2 not installed"
                return self._extract_pdf(file_path), ""
            
            elif suffix in ['.docx', '.doc']:
                if not HAS_DOCX:
                    return "", "python-docx not installed"
                return self._extract_docx(file_path), ""
            
            else:
                return "", f"Unsupported file type: {suffix}"
        
        except Exception as e:
            return "", str(e)
    
    def _extract_pdf(self, file_path: Path) -> str:
        """Extract text from PDF."""
        text_parts = []
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
        return "\n\n".join(text_parts)
    
    def _extract_docx(self, file_path: Path) -> str:
        """Extract text from DOCX."""
        doc = Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)
    
    # -------------------------------------------------------------------------
    # CATEGORY DETECTION
    # -------------------------------------------------------------------------
    
    def _detect_category(self, filename: str, content: bytes = None) -> str:
        """Auto-detect category from filename and content."""
        text = filename.lower()
        
        # Also check content if available
        if content:
            try:
                text += " " + content.decode('utf-8', errors='ignore').lower()[:5000]
            except:
                pass
        
        # Score each category
        scores = {}
        for cat_id, cat_info in CATEGORIES.items():
            if cat_id == "general":
                continue
            score = sum(1 for kw in cat_info["keywords"] if kw in text)
            if score > 0:
                scores[cat_id] = score
        
        if scores:
            return max(scores, key=scores.get)
        return "general"
    
    # -------------------------------------------------------------------------
    # INGESTION
    # -------------------------------------------------------------------------
    
    async def run_ingestion(self, categories: List[str] = None) -> Dict[str, Any]:
        """
        Run Night School ingestion on curriculum files.
        
        Args:
            categories: List of categories to process (None = all)
        
        Returns:
            Ingestion results summary
        """
        results = {
            "started": datetime.datetime.now().isoformat(),
            "files_processed": 0,
            "learnings_added": 0,
            "errors": [],
            "by_category": {}
        }
        
        print("[*] NIGHT SCHOOL: Ingestion session starting...")
        
        # Determine which categories to process
        cats_to_process = categories if categories else list(CATEGORIES.keys())
        
        for cat_id in cats_to_process:
            cat_dir = self.curriculum_dir / cat_id
            if not cat_dir.exists():
                continue
            
            cat_results = {"processed": 0, "added": 0, "skipped": 0, "errors": []}
            
            for file_path in cat_dir.iterdir():
                if file_path.is_file() and not file_path.name.startswith('.'):
                    # Check if already ingested
                    marker = cat_dir / f".ingested_{file_path.name}"
                    if marker.exists():
                        cat_results["skipped"] += 1
                        continue
                    
                    # Extract content
                    content, error = self.extract_content(file_path)
                    
                    if error:
                        cat_results["errors"].append(f"{file_path.name}: {error}")
                        results["errors"].append(f"{cat_id}/{file_path.name}: {error}")
                        continue
                    
                    if len(content) < 20:
                        cat_results["skipped"] += 1
                        continue
                    
                    # Add to learnings
                    print(f"   [NIGHT SCHOOL] Ingesting: {file_path.name} → {cat_id}")
                    
                    self.add_learning(
                        content=content,
                        source=f"CURRICULUM_{cat_id.upper()}",
                        filename=file_path.name,
                        category=cat_id
                    )
                    
                    # Mark as ingested
                    marker.touch()
                    
                    cat_results["processed"] += 1
                    cat_results["added"] += 1
                    results["files_processed"] += 1
                    results["learnings_added"] += 1
            
            results["by_category"][cat_id] = cat_results
        
        # Also process inbox (auto-categorize)
        inbox_dir = self.curriculum_dir / "_inbox"
        if inbox_dir.exists():
            inbox_results = {"processed": 0, "added": 0, "moved": [], "errors": []}
            
            for file_path in inbox_dir.iterdir():
                if file_path.is_file() and not file_path.name.startswith('.'):
                    content, error = self.extract_content(file_path)
                    
                    if error:
                        inbox_results["errors"].append(f"{file_path.name}: {error}")
                        continue
                    
                    # Auto-detect category
                    detected_cat = self._detect_category(file_path.name, content.encode() if content else None)
                    
                    # Move to detected category
                    if self.move_to_category(file_path.name, "_inbox", detected_cat):
                        inbox_results["moved"].append({
                            "file": file_path.name,
                            "category": detected_cat
                        })
                        
                        # Now ingest from new location
                        new_path = self.curriculum_dir / detected_cat / file_path.name
                        if new_path.exists() and len(content) >= 20:
                            self.add_learning(
                                content=content,
                                source=f"CURRICULUM_{detected_cat.upper()}",
                                filename=file_path.name,
                                category=detected_cat
                            )
                            
                            # Mark as ingested
                            (new_path.parent / f".ingested_{file_path.name}").touch()
                            
                            inbox_results["added"] += 1
                            results["learnings_added"] += 1
                    
                    inbox_results["processed"] += 1
                    results["files_processed"] += 1
            
            results["by_category"]["_inbox"] = inbox_results
        
        # Synthesize wisdom
        await self._synthesize_wisdom()
        
        results["completed"] = datetime.datetime.now().isoformat()
        print(f"[*] NIGHT SCHOOL: Ingestion complete. {results['learnings_added']} learnings added.")
        
        return results
    
    def add_learning(self, content: str, source: str, filename: str = "", category: str = "general"):
        """Add a learning entry to the history."""
        learnings = self._load_json(self.learnings_file, [])
        
        # Check for duplicates
        content_hash = hashlib.md5(content.encode()).hexdigest()
        for entry in learnings:
            if entry.get("content_hash") == content_hash:
                return None  # Skip duplicate
        
        entry = {
            "id": secrets.token_hex(8),
            "content": content[:10000],  # Limit content size
            "content_hash": content_hash,
            "source": source,
            "filename": filename,
            "category": category,
            "timestamp": datetime.datetime.now().isoformat(),
            "times_applied": 0,
            "effectiveness_score": 0.5,
            "deprecated": False
        }
        
        learnings.append(entry)
        self._save_json(self.learnings_file, learnings[-2000:])  # Keep last 2000
        
        return entry["id"]
    
    async def _synthesize_wisdom(self):
        """Synthesize learnings into structured wisdom."""
        learnings = self._load_json(self.learnings_file, [])
        
        if not learnings:
            return
        
        active_learnings = [l for l in learnings if not l.get("deprecated", False)]
        
        # Group by category
        by_category = {}
        for l in active_learnings:
            cat = l.get("category", "general")
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(l)
        
        # Build wisdom structure
        wisdom = {
            "version": "2.0",
            "last_synthesis": datetime.datetime.now().isoformat(),
            "total_learnings": len(active_learnings),
            "categories": {},
            "entries": []
        }
        
        # Process each category
        for cat_id, cat_learnings in by_category.items():
            cat_info = CATEGORIES.get(cat_id, {"name": cat_id, "description": ""})
            
            wisdom["categories"][cat_id] = {
                "name": cat_info["name"],
                "description": cat_info["description"],
                "count": len(cat_learnings),
                "summary": self._summarize_category(cat_learnings)
            }
            
            # Add entries (most recent first)
            for l in sorted(cat_learnings, key=lambda x: x.get("timestamp", ""), reverse=True)[:20]:
                wisdom["entries"].append({
                    "id": l["id"],
                    "category": cat_id,
                    "content": l["content"][:500],
                    "source": l["source"],
                    "filename": l.get("filename", ""),
                    "timestamp": l["timestamp"],
                    "confidence": l.get("effectiveness_score", 0.5)
                })
        
        # Create accumulated learnings text
        accumulated = []
        for cat_id, cat_data in wisdom["categories"].items():
            if cat_data["summary"]:
                accumulated.append(f"[{cat_data['name'].upper()}]\n{cat_data['summary']}")
        
        wisdom["accumulated_learnings"] = "\n\n".join(accumulated)
        
        self._save_json(self.wisdom_file, wisdom)
    
    def _summarize_category(self, learnings: List[Dict]) -> str:
        """Create a brief summary of learnings in a category."""
        if not learnings:
            return ""
        
        # Get unique key points (first 100 chars of each)
        points = []
        seen = set()
        for l in learnings[-10:]:  # Last 10 entries
            snippet = l["content"][:100].strip()
            if snippet and snippet not in seen:
                seen.add(snippet)
                points.append(f"• {snippet}...")
        
        return "\n".join(points[:5])  # Max 5 points
    
    # -------------------------------------------------------------------------
    # WISDOM ACCESS
    # -------------------------------------------------------------------------
    
    def get_wisdom(self) -> Dict[str, Any]:
        """Get the full wisdom structure."""
        return self._load_json(self.wisdom_file, {
            "version": "2.0",
            "accumulated_learnings": "",
            "categories": {},
            "entries": []
        })
    
    def get_wisdom_for_category(self, category: str) -> Dict[str, Any]:
        """Get wisdom entries for a specific category."""
        wisdom = self.get_wisdom()
        entries = [e for e in wisdom.get("entries", []) if e.get("category") == category]
        return {
            "category": category,
            "info": wisdom.get("categories", {}).get(category, {}),
            "entries": entries
        }
    
    def get_accumulated_learnings(self) -> str:
        """Get the accumulated learnings text for injection into AI context."""
        wisdom = self.get_wisdom()
        return wisdom.get("accumulated_learnings", "")
    
    # -------------------------------------------------------------------------
    # UTILITIES
    # -------------------------------------------------------------------------
    
    def _load_json(self, path: Path, default: Any = None) -> Any:
        if default is None:
            default = {}
        if not path.exists():
            return default
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except:
            return default
    
    def _save_json(self, path: Path, data: Any) -> bool:
        try:
            with open(path, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            return True
        except:
            return False


# =============================================================================
# WEBSOCKET HANDLERS
# =============================================================================

"""
Add these handlers to bridge_server.py:

# Initialize
night_school_curriculum = NightSchoolCurriculum(VAULT_ROOT)

# Handlers:

elif t == "get_curriculum_structure":
    if current_profile and current_profile.get("role") == "ADMIN":
        structure = night_school_curriculum.get_folder_structure()
        await websocket.send(json.dumps({
            "type": "curriculum_structure",
            "data": structure,
            "categories": CATEGORIES
        }))

elif t == "upload_curriculum_file":
    if current_profile and current_profile.get("role") == "ADMIN":
        import base64
        filename = d.get("filename", "upload.txt")
        content_b64 = d.get("content", "")
        category = d.get("category", "_inbox")
        
        content = base64.b64decode(content_b64)
        result = night_school_curriculum.upload_file(filename, content, category)
        
        await websocket.send(json.dumps({
            "type": "file_uploaded" if result.get("success") else "error",
            "data": result
        }))

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
            "to_category": d.get("to_category")
        }))

elif t == "delete_curriculum_file":
    if current_profile and current_profile.get("role") == "ADMIN":
        success = night_school_curriculum.delete_file(
            d.get("filename"),
            d.get("category")
        )
        await websocket.send(json.dumps({
            "type": "file_deleted" if success else "error"
        }))

elif t == "run_curriculum_ingestion":
    if current_profile and current_profile.get("role") == "ADMIN":
        categories = d.get("categories")  # None = all
        
        await websocket.send(json.dumps({
            "type": "ingestion_started"
        }))
        
        results = await night_school_curriculum.run_ingestion(categories)
        
        await websocket.send(json.dumps({
            "type": "ingestion_complete",
            "results": results
        }))

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
"""


# =============================================================================
# CLI USAGE
# =============================================================================

if __name__ == "__main__":
    import asyncio
    
    # Test with local folder
    test_root = Path("./test_vaults")
    curriculum = NightSchoolCurriculum(test_root)
    
    print("\n📁 Folder Structure:")
    structure = curriculum.get_folder_structure()
    print(json.dumps(structure, indent=2))
    
    print("\n📂 Categories:")
    for cat_id, cat_info in CATEGORIES.items():
        print(f"  {cat_id}: {cat_info['name']}")
