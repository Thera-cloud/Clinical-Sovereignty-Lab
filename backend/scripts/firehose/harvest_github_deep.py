"""
GitHub Deep Repository Harvester — Phase 2a
Clones trending/curated repos, parses actual code files, docstrings,
and architectural patterns into fragments.

Target: 5,000–10,000 crystals across coding + defense domains.
Node: ORANGE (Hetzner) → ships to GREEN.

Usage:
  python -m backend.scripts.firehose.harvest_github_deep
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

FIREHOSE_DIR = Path(__file__).parent
sys.path.insert(0, str(FIREHOSE_DIR))
from progress_tracker import ProgressTracker

GREEN_PUSH_URL = os.getenv("GREEN_PUSH_URL", "http://localhost:8000/api/admin/crystal-network/push")
GREEN_AUTH_TOKEN = os.getenv("GREEN_AUTH_TOKEN", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

MAX_FILE_SIZE = 50_000
MAX_FRAGMENT_LEN = 2000
STAGE1_THRESHOLD = 6
PUSH_BATCH_SIZE = 50
CLONE_DIR = os.getenv("FIREHOSE_CLONE_DIR", "/tmp/firehose_clones")

EXTENSIONS_TO_SCAN = {
    ".py", ".ts", ".js", ".go", ".rs", ".java", ".rb", ".sh",
    ".sql", ".yml", ".yaml", ".md", ".dockerfile",
}

CURATED_REPOS = [
    "fastapi/fastapi", "pallets/flask", "django/django",
    "tiangolo/sqlmodel", "encode/httpx", "aio-libs/aiohttp",
    "psycopg/psycopg", "MagicStack/asyncpg",
    "langchain-ai/langchain", "openai/openai-python",
    "huggingface/transformers", "pytorch/pytorch",
    "grafana/grafana", "prometheus/prometheus",
    "docker/compose", "kubernetes/kubernetes",
    "hashicorp/terraform", "ansible/ansible",
    "owasp/owasp-testing-guide-v4", "zaproxy/zaproxy",
    "jina-ai/jina", "qdrant/qdrant",
    "cloudflare/workers-sdk", "cloudflare/miniflare",
]


def extract_python_fragments(filepath: Path, repo_name: str) -> List[Dict]:
    """Extract docstrings, function signatures, and class architectures."""
    fragments = []
    try:
        content = filepath.read_text(errors="ignore")
    except Exception:
        return []

    if len(content) > MAX_FILE_SIZE:
        return []

    import ast
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            docstring = ast.get_docstring(node)
            if docstring and len(docstring) > 40:
                sig = f"def {node.name}("
                args = [a.arg for a in node.args.args[:8]]
                sig += ", ".join(args) + ")"
                text = f"[Python Function Pattern: {repo_name}]\n{sig}\n\n{docstring}"
                fragments.append({
                    "text": text[:MAX_FRAGMENT_LEN],
                    "source": f"github:{repo_name}:{filepath.name}:{node.name}",
                    "domain": "coding",
                })

        elif isinstance(node, ast.ClassDef):
            docstring = ast.get_docstring(node)
            if docstring and len(docstring) > 40:
                methods = [n.name for n in ast.walk(node)
                           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                           and not n.name.startswith("_")][:10]
                text = (
                    f"[Python Class Architecture: {repo_name}]\n"
                    f"class {node.name}:\n"
                    f"  Public methods: {', '.join(methods)}\n\n"
                    f"{docstring}"
                )
                fragments.append({
                    "text": text[:MAX_FRAGMENT_LEN],
                    "source": f"github:{repo_name}:{filepath.name}:{node.name}",
                    "domain": "coding",
                })

    module_doc = ast.get_docstring(tree)
    if module_doc and len(module_doc) > 60:
        fragments.append({
            "text": f"[Python Module: {repo_name}/{filepath.name}]\n\n{module_doc}",
            "source": f"github:{repo_name}:{filepath.name}:module",
            "domain": "coding",
        })

    return fragments


def extract_readme_fragments(filepath: Path, repo_name: str) -> List[Dict]:
    """Extract sections from README/markdown files."""
    try:
        content = filepath.read_text(errors="ignore")
    except Exception:
        return []

    if len(content) < 100 or len(content) > MAX_FILE_SIZE:
        return []

    fragments = []
    sections = re.split(r"\n#{1,3}\s+", content)
    for i, section in enumerate(sections):
        if len(section.strip()) < 80:
            continue
        text = section.strip()[:MAX_FRAGMENT_LEN]
        fragments.append({
            "text": f"[Documentation: {repo_name}]\n{text}",
            "source": f"github:{repo_name}:{filepath.name}:section_{i}",
            "domain": "coding",
        })

    return fragments


def extract_generic_fragments(filepath: Path, repo_name: str) -> List[Dict]:
    """Extract meaningful fragments from non-Python source files."""
    try:
        content = filepath.read_text(errors="ignore")
    except Exception:
        return []

    if len(content) < 100 or len(content) > MAX_FILE_SIZE:
        return []

    fragments = []
    comment_blocks = re.findall(
        r"(?:(?://|#)\s*.+\n){3,}|/\*[\s\S]{60,}?\*/",
        content,
    )
    for i, block in enumerate(comment_blocks[:5]):
        clean = re.sub(r"^(?://|#|\*)\s*", "", block, flags=re.MULTILINE).strip()
        if len(clean) > 60:
            fragments.append({
                "text": f"[Code Comment Pattern: {repo_name}/{filepath.name}]\n{clean}"[:MAX_FRAGMENT_LEN],
                "source": f"github:{repo_name}:{filepath.name}:comment_{i}",
                "domain": "coding",
            })

    return fragments


def clone_repo(repo: str) -> Optional[Path]:
    """Shallow-clone a repo, return the path or None on failure."""
    dest = Path(CLONE_DIR) / repo.replace("/", "_")
    if dest.exists():
        return dest

    url = f"https://github.com/{repo}.git"
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", "--single-branch", url, str(dest)],
            capture_output=True, timeout=120,
        )
        if dest.exists():
            return dest
    except Exception as e:
        print(f"  [GITHUB] Clone failed for {repo}: {e}")
    return None


def stage1_filter(text: str) -> Optional[int]:
    from common import stage1_ollama_score
    prompt = (
        f"Score this code-related fragment 1-10 for value as crystallized knowledge.\n"
        f"Consider: specificity, pattern reusability, architectural insight, security relevance.\n"
        f"Respond with ONLY a number 1-10.\n\n{text[:1000]}"
    )
    return stage1_ollama_score(text, prompt)


def push_to_green(fragments: List[Dict]):
    from common import push_to_green_safe
    push_to_green_safe(
        fragments, domain_default="coding", fallback_name="github",
        green_push_url=GREEN_PUSH_URL, green_auth_token=GREEN_AUTH_TOKEN or "",
        face_path_prefix="github",
    )


def fetch_trending_repos() -> List[str]:
    """Fetch trending repos from GitHub API (past week)."""
    import requests
    from datetime import datetime, timedelta
    week_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    try:
        resp = requests.get(
            "https://api.github.com/search/repositories",
            params={
                "q": f"created:>{week_ago} language:python",
                "sort": "stars",
                "per_page": 20,
            },
            headers={"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {},
            timeout=30,
        )
        if resp.status_code == 200:
            return [item["full_name"] for item in resp.json().get("items", [])]
    except Exception:
        pass
    return []


def harvest_github():
    tracker = ProgressTracker()
    tracker.set_status("current_phase", "github_deep")
    os.makedirs(CLONE_DIR, exist_ok=True)

    repos = list(CURATED_REPOS)
    trending = fetch_trending_repos()
    for t in trending:
        if t not in repos:
            repos.append(t)

    total_passed = 0
    push_buffer: List[Dict] = []

    for repo in repos:
        if tracker.is_done("github_deep", f"repo:{repo}"):
            continue

        tracker.set_status("current_source", repo)
        print(f"\n[GITHUB] Cloning {repo}...")
        repo_path = clone_repo(repo)
        if not repo_path:
            tracker.mark_done("github_deep", f"repo:{repo}", domain="coding", passed=False)
            continue

        all_frags: List[Dict] = []
        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d not in {
                ".git", "node_modules", "__pycache__", ".venv", "vendor",
                "dist", "build", ".tox", ".mypy_cache",
            }]
            for fname in files:
                fp = Path(root) / fname
                suffix = fp.suffix.lower()
                if suffix not in EXTENSIONS_TO_SCAN:
                    continue

                if suffix == ".py":
                    all_frags.extend(extract_python_fragments(fp, repo))
                elif suffix == ".md":
                    all_frags.extend(extract_readme_fragments(fp, repo))
                else:
                    all_frags.extend(extract_generic_fragments(fp, repo))

        print(f"  [{repo}] Extracted {len(all_frags)} raw fragments")

        for frag in all_frags:
            frag_id = hashlib.sha256(frag["source"].encode()).hexdigest()[:16]
            if tracker.is_done("github_deep", frag_id):
                continue

            score = stage1_filter(frag["text"])
            passed = score is not None and score >= STAGE1_THRESHOLD
            tracker.mark_done("github_deep", frag_id, domain="coding", passed=passed)

            if passed:
                total_passed += 1
                frag["quality_score"] = score
                push_buffer.append(frag)

                if len(push_buffer) >= PUSH_BATCH_SIZE:
                    push_to_green(push_buffer)
                    push_buffer.clear()

        tracker.mark_done("github_deep", f"repo:{repo}", domain="coding", passed=True)

        try:
            shutil.rmtree(repo_path)
        except Exception:
            pass

    if push_buffer:
        push_to_green(push_buffer)

    tracker.set_status("current_source", "complete")
    tracker.write_status_json()
    print(f"\n[GITHUB] Complete — {total_passed} fragments passed Stage 1")
    tracker.close()


if __name__ == "__main__":
    harvest_github()
