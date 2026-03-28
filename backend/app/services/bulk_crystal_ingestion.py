"""
Bulk Crystal Ingestion — Acceleration Levers for EXA-Level Knowledge Density.

Four ingestion modes that mass-seed the code intelligence crystal graph:

  Lever 1 — Codebase Bulk: Scans the local repo, extracts per-file summaries,
            and crystallizes architecture-level patterns.
  Lever 2 — GitHub Mass:   Fetches trending repos and high-star projects via
            GitHub API, distills README + core file patterns.
  Lever 3 — StackOverflow Dump: Queries StackExchange API for top-voted answers
            on the tech stack, crystallizes battle-tested solutions.
  Lever 4 — Synthesis Budget Acceleration: Runs the crystallizer's cluster+synthesize
            cycle at 4x normal frequency during bulk ingestion windows.

All ingested fragments go through the standard NateMemoryCrystallizer pipeline
(validator, clustering, synthesis) before becoming crystals.  Pruning (not
decay) applies: code crystals are pruned only on confidence < C_emo-aware floor
or supersession, never on age.

Usage:
  # From main.py lifespan or admin API:
  ingestion = BulkCrystalIngestion(db_pool, app_state)
  await ingestion.run_codebase_scan()     # Lever 1
  await ingestion.run_github_trending()   # Lever 2
  await ingestion.run_stackoverflow()     # Lever 3
  await ingestion.run_synthesis_burst()   # Lever 4
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TECH_EXTENSIONS = {
    ".py", ".dart", ".js", ".ts", ".tsx", ".jsx",
    ".sql", ".sh", ".yml", ".yaml", ".toml",
    ".html", ".css", ".mdc",
}

SKIP_DIRS = {
    "__pycache__", "node_modules", ".git", ".cursor",
    "archive", "build", ".dart_tool", ".pub-cache",
    "venv", ".venv", "little_nate_v_1_3",
}

MAX_FILE_SIZE = 50_000
BATCH_SIZE = 20
GITHUB_API = "https://api.github.com"
SO_API = "https://api.stackexchange.com/2.3"

STACK_TAGS = [
    "python", "fastapi", "flutter", "dart", "postgresql",
    "redis", "asyncio", "websocket", "docker", "cloudflare-workers",
    "react", "tailwindcss", "typescript", "javascript",
]


class BulkCrystalIngestion:
    """Mass-seed code intelligence crystals from multiple sources."""

    def __init__(self, db_pool=None, app_state=None):
        self._db_pool = db_pool
        self._app_state = app_state
        self._crystallizer = getattr(app_state, "crystallizer", None) if app_state else None
        self._inference_router = getattr(app_state, "inference_router", None) if app_state else None

    # ------------------------------------------------------------------
    # Lever 1: Codebase Bulk Scan
    # ------------------------------------------------------------------

    async def run_codebase_scan(self, root: Optional[str] = None) -> Dict[str, Any]:
        """Scan the local codebase and crystallize per-file architecture patterns."""
        root = root or os.getenv("CODEBASE_ROOT", "/opt/clinical-sovereignty-lab")
        root_path = Path(root)
        if not root_path.exists():
            logger.warning("BulkIngestion: codebase root %s does not exist", root)
            return {"status": "skipped", "reason": "root not found"}

        files_processed = 0
        fragments_created = 0

        for dirpath, dirnames, filenames in os.walk(root_path):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            rel_dir = os.path.relpath(dirpath, root_path)

            for fname in filenames:
                ext = os.path.splitext(fname)[1]
                if ext not in TECH_EXTENSIONS:
                    continue

                fpath = os.path.join(dirpath, fname)
                try:
                    size = os.path.getsize(fpath)
                    if size > MAX_FILE_SIZE or size < 50:
                        continue

                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()

                    rel_path = os.path.join(rel_dir, fname)
                    summary = self._extract_file_summary(content, rel_path, ext)
                    if not summary:
                        continue

                    content_hash = hashlib.sha256(summary.encode()).hexdigest()[:16]
                    if await self._crystal_exists(content_hash):
                        continue

                    fragment = {
                        "text": f"[CODEBASE] {rel_path}\n\n{summary}",
                        "source": f"codebase_bulk:{rel_path}",
                        "domain": "coding",
                        "scope": "global",
                        "topics": self._infer_topics(content, ext),
                        "created_at": datetime.now(timezone.utc),
                    }

                    if self._crystallizer:
                        self._crystallizer._harvest_buffer.append(fragment)
                        fragments_created += 1

                    files_processed += 1
                    if files_processed % 50 == 0:
                        await asyncio.sleep(0.01)

                except Exception as e:
                    logger.debug("BulkIngestion: skipped %s: %s", fname, e)

        logger.info("BulkIngestion[codebase]: processed %d files, created %d fragments",
                     files_processed, fragments_created)
        return {"files_processed": files_processed, "fragments_created": fragments_created}

    # ------------------------------------------------------------------
    # Lever 2: GitHub Trending
    # ------------------------------------------------------------------

    async def run_github_trending(self, languages: Optional[List[str]] = None) -> Dict[str, Any]:
        """Fetch trending GitHub repos and distill patterns."""
        languages = languages or ["python", "dart", "typescript"]
        fragments_created = 0

        try:
            import aiohttp
        except ImportError:
            return {"status": "skipped", "reason": "aiohttp not available"}

        async with aiohttp.ClientSession() as session:
            for lang in languages:
                try:
                    url = f"{GITHUB_API}/search/repositories"
                    params = {
                        "q": f"language:{lang} stars:>500 pushed:>2025-01-01",
                        "sort": "stars",
                        "order": "desc",
                        "per_page": 10,
                    }
                    headers = {"Accept": "application/vnd.github.v3+json"}
                    gh_token = os.getenv("GITHUB_TOKEN", "")
                    if gh_token:
                        headers["Authorization"] = f"token {gh_token}"

                    async with session.get(url, params=params, headers=headers,
                                           timeout=aiohttp.ClientTimeout(total=20)) as resp:
                        if resp.status != 200:
                            logger.warning("BulkIngestion[github]: %s returned %d", lang, resp.status)
                            continue
                        data = await resp.json()

                    for repo in data.get("items", [])[:10]:
                        name = repo.get("full_name", "")
                        description = repo.get("description", "") or ""
                        stars = repo.get("stargazers_count", 0)
                        topics = repo.get("topics", [])[:5]

                        readme_text = await self._fetch_readme(session, name, headers)

                        summary = (
                            f"Repository: {name} ({stars:,} stars)\n"
                            f"Description: {description}\n"
                            f"Topics: {', '.join(topics)}\n\n"
                            f"{readme_text[:1500]}"
                        )

                        content_hash = hashlib.sha256(
                            (name + description).encode()
                        ).hexdigest()[:16]
                        if await self._crystal_exists(content_hash):
                            continue

                        fragment = {
                            "text": f"[GITHUB] {summary}",
                            "source": f"github_mass:{name}",
                            "domain": "coding",
                            "scope": "global",
                            "topics": topics + [lang],
                            "created_at": datetime.now(timezone.utc),
                        }

                        if self._crystallizer:
                            self._crystallizer._harvest_buffer.append(fragment)
                            fragments_created += 1

                    await asyncio.sleep(1)
                except Exception as e:
                    logger.warning("BulkIngestion[github]: %s failed: %s", lang, e)

        logger.info("BulkIngestion[github]: created %d fragments", fragments_created)
        return {"fragments_created": fragments_created}

    # ------------------------------------------------------------------
    # Lever 3: StackOverflow Top Answers
    # ------------------------------------------------------------------

    async def run_stackoverflow(self, tags: Optional[List[str]] = None) -> Dict[str, Any]:
        """Fetch top-voted SO answers for tech stack and crystallize solutions."""
        tags = tags or STACK_TAGS[:6]
        fragments_created = 0

        try:
            import aiohttp
        except ImportError:
            return {"status": "skipped", "reason": "aiohttp not available"}

        async with aiohttp.ClientSession() as session:
            for tag in tags:
                try:
                    url = f"{SO_API}/questions"
                    params = {
                        "order": "desc",
                        "sort": "votes",
                        "tagged": tag,
                        "site": "stackoverflow",
                        "filter": "withbody",
                        "pagesize": 10,
                    }
                    async with session.get(url, params=params,
                                           timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.json()

                    for item in data.get("items", [])[:10]:
                        title = item.get("title", "")
                        body = re.sub(r"<[^>]+>", "", item.get("body", ""))[:1200]
                        score = item.get("score", 0)
                        q_tags = item.get("tags", [])[:5]

                        content_hash = hashlib.sha256(title.encode()).hexdigest()[:16]
                        if await self._crystal_exists(content_hash):
                            continue

                        fragment = {
                            "text": (
                                f"[STACKOVERFLOW] {title} (score: {score})\n"
                                f"Tags: {', '.join(q_tags)}\n\n{body}"
                            ),
                            "source": f"stackoverflow_dump:{tag}",
                            "domain": "coding",
                            "scope": "global",
                            "topics": q_tags,
                            "created_at": datetime.now(timezone.utc),
                        }

                        if self._crystallizer:
                            self._crystallizer._harvest_buffer.append(fragment)
                            fragments_created += 1

                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.warning("BulkIngestion[stackoverflow]: tag=%s failed: %s", tag, e)

        logger.info("BulkIngestion[stackoverflow]: created %d fragments", fragments_created)
        return {"fragments_created": fragments_created}

    # ------------------------------------------------------------------
    # Lever 4: Synthesis Budget Acceleration (4x burst)
    # ------------------------------------------------------------------

    async def run_synthesis_burst(self, rounds: int = 4) -> Dict[str, Any]:
        """Run the crystallizer's cluster-and-synthesize cycle at 4x frequency."""
        if not self._crystallizer:
            return {"status": "skipped", "reason": "crystallizer not available"}

        crystals_created = 0
        for i in range(rounds):
            try:
                count = await self._crystallizer._cluster_and_synthesize_cycle()
                crystals_created += count or 0
                logger.info("BulkIngestion[synthesis]: round %d/%d created %d crystals",
                            i + 1, rounds, count or 0)
                await asyncio.sleep(2)
            except Exception as e:
                logger.warning("BulkIngestion[synthesis]: round %d failed: %s", i + 1, e)

        logger.info("BulkIngestion[synthesis]: total %d crystals from %d rounds",
                     crystals_created, rounds)
        return {"rounds": rounds, "crystals_created": crystals_created}

    # ------------------------------------------------------------------
    # Lever 5: Deep GitHub Repo Cloning + File-Level Extraction
    # ------------------------------------------------------------------

    async def run_github_deep(
        self,
        repos: Optional[List[str]] = None,
        languages: Optional[List[str]] = None,
        max_repos: int = 5,
    ) -> Dict[str, Any]:
        """Clone repos, walk every source file, and extract per-file crystals.

        Unlike ``run_github_trending`` (Lever 2) which only reads the
        README via the API, this method performs a shallow ``git clone``
        into a temp directory, walks the repo tree, and produces one
        crystal fragment per meaningful source file — extracting
        docstrings, class/function signatures, architectural patterns,
        and inline design rationale.
        """
        languages = languages or ["python", "dart", "typescript"]
        fragments_created = 0
        repos_processed = 0
        tmpdir = tempfile.mkdtemp(prefix="nate_github_deep_")

        try:
            if repos:
                target_repos = repos
            else:
                target_repos = await self._discover_repos(languages, max_repos)

            for repo_url in target_repos:
                repo_name = repo_url.rstrip("/").split("/")[-1]
                clone_dir = os.path.join(tmpdir, repo_name)
                try:
                    proc = await asyncio.to_thread(
                        subprocess.run,
                        ["git", "clone", "--depth", "1", "--single-branch", repo_url, clone_dir],
                        capture_output=True, timeout=60,
                    )
                    if proc.returncode != 0:
                        logger.warning("BulkIngestion[github_deep]: clone failed for %s", repo_url)
                        continue

                    full_name = "/".join(repo_url.rstrip("/").split("/")[-2:]).replace(".git", "")
                    count = await self._walk_repo(clone_dir, full_name)
                    fragments_created += count
                    repos_processed += 1
                    logger.info("BulkIngestion[github_deep]: %s → %d fragments", full_name, count)

                except Exception as e:
                    logger.warning("BulkIngestion[github_deep]: %s failed: %s", repo_url, e)
                finally:
                    shutil.rmtree(clone_dir, ignore_errors=True)

                await asyncio.sleep(0.5)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        logger.info("BulkIngestion[github_deep]: %d repos, %d fragments",
                     repos_processed, fragments_created)
        return {"repos_processed": repos_processed, "fragments_created": fragments_created}

    async def _discover_repos(self, languages: List[str], max_repos: int) -> List[str]:
        """Use GitHub Search API to find high-star repos for cloning."""
        urls: List[str] = []
        try:
            import aiohttp
        except ImportError:
            return urls

        headers = {"Accept": "application/vnd.github.v3+json"}
        gh_token = os.getenv("GITHUB_TOKEN", "")
        if gh_token:
            headers["Authorization"] = f"token {gh_token}"

        async with aiohttp.ClientSession() as session:
            for lang in languages:
                try:
                    params = {
                        "q": f"language:{lang} stars:>1000 pushed:>2025-01-01",
                        "sort": "stars", "order": "desc", "per_page": max_repos,
                    }
                    async with session.get(f"{GITHUB_API}/search/repositories",
                                           params=params, headers=headers,
                                           timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.json()
                    for item in data.get("items", []):
                        clone_url = item.get("clone_url")
                        if clone_url:
                            urls.append(clone_url)
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.warning("BulkIngestion[discover]: %s: %s", lang, e)
        return urls[:max_repos * len(languages)]

    async def _walk_repo(self, repo_dir: str, full_name: str) -> int:
        """Walk a cloned repo and extract per-file crystal fragments."""
        count = 0
        for dirpath, dirnames, filenames in os.walk(repo_dir):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fname in filenames:
                ext = os.path.splitext(fname)[1]
                if ext not in TECH_EXTENSIONS:
                    continue
                fpath = os.path.join(dirpath, fname)
                try:
                    size = os.path.getsize(fpath)
                    if size > MAX_FILE_SIZE or size < 80:
                        continue
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    rel_path = os.path.relpath(fpath, repo_dir)
                    summary = self._extract_deep_summary(content, rel_path, ext)
                    if not summary or len(summary) < 40:
                        continue
                    content_hash = hashlib.sha256(
                        (full_name + ":" + rel_path).encode()
                    ).hexdigest()[:16]
                    if await self._crystal_exists(content_hash):
                        continue

                    fragment = {
                        "text": f"[GITHUB_DEEP] {full_name}/{rel_path}\n\n{summary}",
                        "source": f"github_deep:{full_name}/{rel_path}",
                        "domain": "coding",
                        "scope": "global",
                        "topics": self._infer_topics(content, ext) + [full_name.split("/")[0]],
                        "created_at": datetime.now(timezone.utc),
                    }
                    if self._crystallizer:
                        self._crystallizer._harvest_buffer.append(fragment)
                        count += 1
                    if count % 50 == 0:
                        await asyncio.sleep(0.01)
                except Exception:
                    continue
        return count

    def _extract_deep_summary(self, content: str, path: str, ext: str) -> Optional[str]:
        """Rich extraction: docstrings, class/method sigs, design comments."""
        lines = content.split("\n")
        if len(lines) < 5:
            return None

        parts: List[str] = []

        if ext == ".py":
            triple = re.search(r'"""(.*?)"""', content, re.DOTALL)
            if triple:
                parts.append(triple.group(1).strip()[:600])
            classes = re.findall(r"^class (\w+).*?:", content, re.MULTILINE)
            if classes:
                parts.append("Classes: " + ", ".join(classes[:15]))
            funcs = re.findall(r"^(?:async )?def (\w+)\(([^)]{0,120})\)", content, re.MULTILINE)
            sigs = [f"{n}({a})" for n, a in funcs if not n.startswith("_")][:15]
            if sigs:
                parts.append("Public API:\n  " + "\n  ".join(sigs))
            design = [l.strip().lstrip("# ") for l in lines
                       if l.strip().startswith("#") and any(
                           kw in l.lower() for kw in (
                               "why", "trade", "note:", "caveat", "important",
                               "design", "architecture", "rationale"))][:5]
            if design:
                parts.append("Design notes:\n  " + "\n  ".join(design))

        elif ext == ".dart":
            classes = re.findall(r"^class (\w+)", content, re.MULTILINE)
            if classes:
                parts.append("Classes: " + ", ".join(classes[:15]))
            docs = re.findall(r"///\s*(.+)", content)[:10]
            if docs:
                parts.append("Docs:\n  " + "\n  ".join(docs))

        elif ext in (".ts", ".tsx", ".js", ".jsx"):
            exports = re.findall(
                r"export (?:default )?(?:function|class|const|interface) (\w+)", content)
            if exports:
                parts.append("Exports: " + ", ".join(exports[:15]))
            jsdoc = re.findall(r"/\*\*(.*?)\*/", content, re.DOTALL)
            if jsdoc:
                parts.append(jsdoc[0].strip()[:400])

        elif ext == ".sql":
            tables = re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?(\w+)", content, re.IGNORECASE)
            if tables:
                parts.append("Tables: " + ", ".join(tables[:10]))

        if not parts:
            first = "\n".join(lines[:25])
            if len(first) > 50:
                parts.append(first[:600])

        if not parts:
            return None
        return f"File: {path}\n" + "\n".join(parts)

    # ------------------------------------------------------------------
    # Lever 6: Stack Overflow XML Dump Ingestion
    # ------------------------------------------------------------------

    async def run_stackoverflow_dump(
        self,
        posts_xml_path: str,
        max_posts: int = 50_000,
        min_score: int = 10,
        tags_filter: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Ingest crystals from a real Stack Overflow data dump XML file.

        The official dump (``Posts.xml``) is downloadable from
        ``archive.org/details/stackexchange``.  This method parses the
        XML iteratively (no full DOM load), filters for accepted answers
        with sufficient score and matching tags, strips HTML, and creates
        one crystal fragment per answer.

        Args:
            posts_xml_path: Absolute path to the ``Posts.xml`` file.
            max_posts: Cap on total fragments to create.
            min_score: Minimum post score to include.
            tags_filter: If provided, only include posts whose tags
                         overlap with this list (e.g. ``STACK_TAGS``).
        """
        tags_filter = tags_filter or STACK_TAGS
        tags_set = set(tags_filter) if tags_filter else None
        fragments_created = 0
        posts_scanned = 0

        if not os.path.isfile(posts_xml_path):
            logger.warning("BulkIngestion[so_dump]: file not found: %s", posts_xml_path)
            return {"status": "skipped", "reason": "file_not_found"}

        try:
            context = ET.iterparse(posts_xml_path, events=("end",))
            for event, elem in context:
                if elem.tag != "row":
                    continue

                post_type = elem.get("PostTypeId", "")
                if post_type != "2":
                    elem.clear()
                    continue

                score = int(elem.get("Score", "0"))
                if score < min_score:
                    elem.clear()
                    continue

                tags_raw = elem.get("Tags", "")
                if tags_set:
                    post_tags = set(re.findall(r"<(.+?)>", tags_raw))
                    if not post_tags & tags_set:
                        parent_id = elem.get("ParentId", "")
                        elem.clear()
                        continue
                else:
                    post_tags = set(re.findall(r"<(.+?)>", tags_raw))

                body_html = elem.get("Body", "")
                body_text = re.sub(r"<[^>]+>", "", unescape(body_html))[:2000]

                if len(body_text) < 80:
                    elem.clear()
                    continue

                post_id = elem.get("Id", "")
                content_hash = hashlib.sha256(
                    f"so_dump:{post_id}".encode()
                ).hexdigest()[:16]

                if await self._crystal_exists(content_hash):
                    elem.clear()
                    continue

                tag_list = sorted(post_tags)[:6]
                fragment = {
                    "text": (
                        f"[SO_DUMP] Answer #{post_id} (score: {score})\n"
                        f"Tags: {', '.join(tag_list)}\n\n{body_text}"
                    ),
                    "source": f"so_dump:{post_id}",
                    "domain": "coding",
                    "scope": "global",
                    "topics": tag_list,
                    "created_at": datetime.now(timezone.utc),
                }

                if self._crystallizer:
                    self._crystallizer._harvest_buffer.append(fragment)
                    fragments_created += 1

                posts_scanned += 1
                elem.clear()

                if fragments_created >= max_posts:
                    break

                if fragments_created % 500 == 0:
                    await asyncio.sleep(0.01)
                    logger.info(
                        "BulkIngestion[so_dump]: %d fragments from %d posts scanned",
                        fragments_created, posts_scanned)

        except ET.ParseError as e:
            logger.error("BulkIngestion[so_dump]: XML parse error at post %d: %s",
                         posts_scanned, e)
        except Exception as e:
            logger.error("BulkIngestion[so_dump]: unexpected error: %s", e)

        logger.info("BulkIngestion[so_dump]: %d fragments created from %d posts",
                     fragments_created, posts_scanned)
        return {"posts_scanned": posts_scanned, "fragments_created": fragments_created}

    # ------------------------------------------------------------------
    # Combined run: all 4 levers sequentially
    # ------------------------------------------------------------------

    async def run_full_acceleration(self, include_deep: bool = False, so_dump_path: Optional[str] = None) -> Dict[str, Any]:
        """Execute all acceleration levers in sequence, then push to edge.

        Args:
            include_deep: If True, runs Lever 5 (deep GitHub cloning).
            so_dump_path: Path to a Stack Overflow ``Posts.xml`` dump.
                          When provided, runs Lever 6 instead of the
                          shallow API-based Lever 3.
        """
        logger.info("BulkIngestion: starting full acceleration run")
        results = {}

        results["codebase"] = await self.run_codebase_scan()
        results["github"] = await self.run_github_trending()
        if include_deep:
            results["github_deep"] = await self.run_github_deep()
        if so_dump_path:
            results["so_dump"] = await self.run_stackoverflow_dump(so_dump_path)
        else:
            results["stackoverflow"] = await self.run_stackoverflow()
        results["synthesis"] = await self.run_synthesis_burst()

        total = sum(
            r.get("fragments_created", 0) + r.get("crystals_created", 0)
            for r in results.values()
        )
        results["total_items"] = total

        push_result = await self._push_to_edge_kv()
        results["edge_push"] = push_result

        logger.info("BulkIngestion: full acceleration complete — %d total items, %d pushed to edge",
                     total, push_result.get("pushed", 0))
        return results

    # ------------------------------------------------------------------
    # Post-Ingestion Edge KV Push
    # ------------------------------------------------------------------

    async def _push_to_edge_kv(self, limit: int = 100) -> Dict[str, Any]:
        """
        Push top-confidence code crystals to R2 manifest for cron worker
        pre-warming.  The cron worker reads this manifest hourly and writes
        each crystal to SUMMON_CACHE KV for 5ms edge retrieval.

        This replaces the Bulk Redirect Lists approach with a direct
        R2 manifest → cron worker → KV pipeline at zero cost.
        """
        if not self._db_pool:
            return {"status": "skipped", "reason": "no_db"}

        r2_storage = getattr(self._app_state, "r2_storage", None) if self._app_state else None

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT id::text, crystal_text, confidence, recall_count, topics
                    FROM nate_intelligence_crystals
                    WHERE domain = 'coding'
                      AND scope != 'archived'
                      AND superseded_by IS NULL
                      AND confidence >= 0.4
                    ORDER BY recall_count DESC, confidence DESC
                    LIMIT $1
                """, limit)

            crystals = []
            for row in rows:
                crystals.append({
                    "id": row["id"],
                    "text": row["crystal_text"][:2000],
                    "confidence": float(row["confidence"]),
                    "recall_count": row["recall_count"],
                    "topics": row["topics"] if isinstance(row["topics"], list) else [],
                })

            manifest = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source": "bulk_ingestion_push",
                "crystal_count": len(crystals),
                "crystals": crystals,
            }

            if r2_storage:
                try:
                    await asyncio.to_thread(
                        r2_storage.upload_bytes,
                        json.dumps(manifest).encode(),
                        "code_crystals/prewarm_manifest.json",
                        content_type="application/json",
                    )
                    logger.info("BulkIngestion: pushed %d crystals to R2 prewarm manifest",
                                len(crystals))
                except Exception as e:
                    logger.warning("BulkIngestion: R2 manifest push failed: %s", e)

            return {"status": "ok", "pushed": len(crystals)}
        except Exception as e:
            logger.warning("BulkIngestion: edge KV push failed: %s", e)
            return {"status": "error", "error": str(e)}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_file_summary(self, content: str, path: str, ext: str) -> Optional[str]:
        """Extract a concise summary from a source file."""
        lines = content.split("\n")
        if len(lines) < 5:
            return None

        summary_parts = []

        # Docstring extraction
        if ext == ".py":
            triple_match = re.search(r'"""(.*?)"""', content, re.DOTALL)
            if triple_match:
                summary_parts.append(triple_match.group(1).strip()[:500])

            classes = re.findall(r"^class (\w+)", content, re.MULTILINE)
            if classes:
                summary_parts.append(f"Classes: {', '.join(classes[:10])}")

            functions = re.findall(r"^(?:async )?def (\w+)", content, re.MULTILINE)
            pub_fns = [f for f in functions if not f.startswith("_")]
            if pub_fns:
                summary_parts.append(f"Public functions: {', '.join(pub_fns[:15])}")

        elif ext == ".dart":
            classes = re.findall(r"^class (\w+)", content, re.MULTILINE)
            if classes:
                summary_parts.append(f"Classes: {', '.join(classes[:10])}")
            doc_match = re.search(r"///(.+)", content)
            if doc_match:
                summary_parts.append(doc_match.group(1).strip())

        elif ext in (".js", ".ts", ".tsx", ".jsx"):
            exports = re.findall(r"export (?:default )?(?:function|class|const) (\w+)", content)
            if exports:
                summary_parts.append(f"Exports: {', '.join(exports[:10])}")

        elif ext == ".sql":
            tables = re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?(\w+)", content, re.IGNORECASE)
            if tables:
                summary_parts.append(f"Tables: {', '.join(tables[:10])}")

        if not summary_parts:
            first_lines = "\n".join(lines[:20])
            if len(first_lines) > 50:
                summary_parts.append(first_lines[:500])

        if not summary_parts:
            return None

        return f"File: {path}\n" + "\n".join(summary_parts)

    def _infer_topics(self, content: str, ext: str) -> List[str]:
        """Infer tech tags from file content and extension."""
        ext_map = {
            ".py": "python", ".dart": "dart", ".js": "javascript",
            ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript",
            ".sql": "postgresql", ".sh": "bash", ".html": "html",
        }
        topics = []
        if ext in ext_map:
            topics.append(ext_map[ext])

        lowered = content.lower()
        for kw in ["fastapi", "flutter", "redis", "asyncio", "websocket",
                    "docker", "cloudflare", "react", "tailwind"]:
            if kw in lowered:
                topics.append(kw)

        return topics[:6] if topics else ["general"]

    async def _crystal_exists(self, content_hash: str) -> bool:
        """Check if a crystal with this hash prefix already exists."""
        if not self._db_pool:
            return False
        try:
            async with self._db_pool.acquire() as conn:
                count = await conn.fetchval("""
                    SELECT COUNT(*) FROM nate_intelligence_crystals
                    WHERE domain = 'coding'
                      AND content_hash LIKE $1 || '%'
                      AND scope != 'archived'
                """, content_hash[:12])
                return (count or 0) > 0
        except Exception:
            return False

    async def _fetch_readme(self, session, repo_name: str, headers: dict) -> str:
        """Fetch README content from GitHub API."""
        try:
            url = f"{GITHUB_API}/repos/{repo_name}/readme"
            async with session.get(url, headers={**headers, "Accept": "application/vnd.github.v3.raw"},
                                   timeout=session.timeout) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    return text[:2000]
        except Exception:
            pass
        return ""
