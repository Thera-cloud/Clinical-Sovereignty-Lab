#!/usr/bin/env python3
"""BLUE node harvester.

Harvests local workspace knowledge, filters with Ollama, and pushes crystals
into GREEN via the crystal-network push endpoint.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import aiohttp
import yaml
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


LOGGER = logging.getLogger("blue_harvester")

_FILTER_RESPONSE_INSTRUCTIONS = """
If PASS, respond with EXACTLY this format:
PASS
DOMAIN: [one of: clinical, coding, coherence, defense, patent, coaching, voice, business, culture]
CRYSTAL: [2-4 sentence crystal text that captures the core knowledge. Write in present tense as a factual statement. Do not reference the source document.]

If FAIL, respond with:
FAIL
REASON: [one sentence explaining why]
""".strip()

FILTER_PROMPTS = {
    "coding": """You are a knowledge filter for an AI coding assistant's permanent memory.
Decide if this text chunk contains coding knowledge worth preserving FOREVER.

PASS if the chunk contains ANY of:
- A deployment pattern, build step, or operational procedure specific to this project
- A configuration choice with WHY it was chosen (not just what)
- An error pattern and its fix (even simple ones — debugging knowledge compounds)
- A file path or module name WITH context about its role in the system
- A Cursor rule (.mdc), linting directive, or development constraint
- A design decision: why this architecture, routing pattern, or data flow
- An anti-pattern or "never do this" with explanation
- A dependency relationship: what calls what, what imports what
- A migration, schema change, or data model decision with reasoning
- Infrastructure logic: Docker, systemd, nginx, Cloudflare config with rationale
- A code pattern that solves a specific class of problems
- Testing strategy, CI/CD logic, or deployment gate criteria
- Performance insight: what's slow, why, how it was fixed
- Security decision: why this auth pattern, encryption choice, access control

FAIL only if:
- Pure auto-generated content with zero human decision (lockfile entries, auto-imports)
- Formatting-only: blank lines, comment dividers, file headers with no substance
- Exact duplicate of previously seen content
- Raw log output with no analysis or pattern

CRITICAL: Err toward PASS. A deployment recipe that prevents 2 hours of debugging
is MORE valuable than a theoretical architecture discussion.""",

    "therapeutic": """You are a knowledge filter for a therapeutic AI's permanent memory.
Decide if this text chunk contains therapeutic knowledge worth preserving FOREVER.

PASS if the chunk contains ANY of:
- Therapeutic concepts, modality descriptions, or clinical frameworks
- Behavioral rules governing AI therapeutic responses
- Crisis detection, escalation logic, or safety boundary rationale
- Client interaction patterns with clinical reasoning
- Nevedal formula application, coherence measurement, or EC calculation
- Attachment theory, polyvagal theory, IFS, AEDP, EFT, MI concepts
- Session structure, pacing, or therapeutic timing principles
- Countertransference awareness or therapeutic boundary rules
- Outcome measurement approaches or effectiveness criteria

FAIL if:
- Generic medical disclaimers or boilerplate consent language
- Pure formatting, structural markup, or UI copy
- Administrative scheduling or billing details without clinical relevance""",

    "architecture": """You are a knowledge filter for a platform architect's permanent memory.
Decide if this text chunk contains architectural knowledge worth preserving FOREVER.

PASS if the chunk contains ANY of:
- System design decisions with rationale (why this pattern)
- Integration patterns between services, APIs, or data stores
- The bridge_server.py routing logic, signal flow, or WebSocket protocol
- Performance, scaling, or cost optimization reasoning
- Infrastructure choices: why Cloudflare, why Hetzner, why DigitalOcean
- The Nevedal formula as a governing equation for system behavior
- ODPE signal routing: LOCKED/PROMOTED/PROVISIONAL/TENSION/DEEP_TENSION/NOISE
- Crystal memory architecture: confidence floors, decay rules, domain scoping
- Patent-relevant architectural novelty

FAIL if:
- Generic cloud documentation without project-specific reasoning
- Pure boilerplate config with no architectural significance""",

    "operations": """You are a knowledge filter for a platform operator's permanent memory.
Decide if this text chunk contains operational knowledge worth preserving FOREVER.

PASS if the chunk contains ANY of:
- Incident response: what broke, why, how it was fixed
- Health check logic, monitoring thresholds, alert criteria
- Deployment procedures specific to this platform
- Database maintenance: vacuum, reindex, backup, migration procedures
- Service restart sequences and dependency ordering
- Capacity planning or resource utilization patterns
- SSL, DNS, domain, or certificate management procedures

FAIL if:
- Generic linux commands without project context
- Auto-generated monitoring output with no analysis""",

    "general": """You are a knowledge filter for an AI system's permanent memory.
Decide if this text chunk contains knowledge worth preserving FOREVER.

PASS if the chunk contains substantive knowledge: a concept, pattern, decision,
insight, framework, or technique that would be useful across multiple future contexts.

FAIL if the chunk is: boilerplate, formatting, auto-generated without substance,
or trivial facts that don't compound.""",
}

SCANNER_DOMAIN_MAP = {
    "SovereignRulesScanner": "coding",
    "CursorRulesScanner": "coding",
    "GitHistoryScanner": "coding",
    "BridgeTherapeuticPromptScanner": "architecture",
    "NightSchoolScanner": "therapeutic",
    "DocumentationScanner": "general",
    "SessionOutputScanner": "therapeutic",
    "GitHubRepoScanner": "coding",
    "StackOverflowScanner": "coding",
    "RSSFeedScanner": "general",
}


def get_filter_prompt(scanner_name: str, chunk_domain: str = "") -> str:
    """Return the domain-appropriate filter prompt for a given scanner."""
    domain = SCANNER_DOMAIN_MAP.get(scanner_name, chunk_domain or "general")
    base = FILTER_PROMPTS.get(domain, FILTER_PROMPTS["general"])
    return base + "\n\n" + _FILTER_RESPONSE_INSTRUCTIONS


BLUE_STAGE1_PROMPT = get_filter_prompt("", "general") + "\n\nTEXT CHUNK:\n{chunk_text}"

HEARTBEAT_URL = os.getenv(
    "BLUE_HEARTBEAT_URL",
    "https://api.sovereignsanctuary.net/api/nate-agent/admin/crystal-heartbeat",
)
HEARTBEAT_TOKEN = os.getenv("SKYEYE_AUDIT_TOKEN", "")


async def report_heartbeat(
    session: aiohttp.ClientSession,
    *,
    status: str = "running",
    chunks_processed: int = 0,
    chunks_total: int = 0,
    chunks_passed: int = 0,
    pass_rate: float = 0.0,
    current_scanner: str = "",
    current_file: str = "",
    crystals_forged: int = 0,
    avg_filter_time_ms: float = 0.0,
) -> None:
    """POST heartbeat to production API. Non-blocking, best-effort."""
    if not HEARTBEAT_TOKEN:
        return
    payload = {
        "node_id": "blue",
        "status": status,
        "crystals_forged": crystals_forged,
        "fragments_harvested": chunks_processed,
        "chunks_processed": chunks_processed,
        "chunks_total": chunks_total,
        "chunks_passed": chunks_passed,
        "pass_rate": round(pass_rate, 3),
        "current_scanner": current_scanner,
        "current_file": current_file,
        "avg_filter_time_ms": round(avg_filter_time_ms, 1),
    }
    try:
        headers = {
            "Authorization": f"Bearer {HEARTBEAT_TOKEN}",
            "Content-Type": "application/json",
        }
        async with session.post(
            HEARTBEAT_URL, json=payload, headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 200:
                LOGGER.debug("Heartbeat OK: %s", status)
            else:
                LOGGER.warning("Heartbeat HTTP %s", resp.status)
    except Exception as exc:
        LOGGER.debug("Heartbeat failed (non-blocking): %s", exc)


ALLOWED_DOMAINS = {
    "clinical",
    "coding",
    "coherence",
    "defense",
    "patent",
    "coaching",
    "voice",
    "business",
    "culture",
    "general",
}

DEFAULT_BRIDGE_PROMPT_RANGES: List[List[int]] = [
    [7458, 7860],
    [7789, 7985],
    [7866, 8195],
    [8201, 8520],
    [8528, 8650],
    [6271, 6310],
    [1312, 1400],
    [8466, 8480],
]


@dataclass
class Chunk:
    text: str
    source_file: str
    scanner_name: str
    domain: str
    metadata: Dict[str, Any] = field(default_factory=dict)


def _clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_markdown_sections(text: str, min_len: int = 100) -> List[str]:
    if not text:
        return []
    chunks: List[str] = []
    current: List[str] = []
    for line in text.splitlines():
        if re.match(r"^#{2,3}\s+", line) and current:
            candidate = _clean_text("\n".join(current))
            if len(candidate) >= min_len:
                chunks.append(candidate)
            current = [line]
        else:
            current.append(line)
    if current:
        candidate = _clean_text("\n".join(current))
        if len(candidate) >= min_len:
            chunks.append(candidate)
    if not chunks:
        text = _clean_text(text)
        if len(text) >= min_len:
            chunks = [text]
    return chunks


def _split_paragraphs(text: str, min_len: int = 120) -> List[str]:
    parts = re.split(r"\n\s*\n", text)
    out: List[str] = []
    for part in parts:
        p = _clean_text(part)
        if len(p) >= min_len:
            out.append(p)
    if not out and len(_clean_text(text)) >= min_len:
        out.append(_clean_text(text))
    return out


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:  # pragma: no cover - defensive
        LOGGER.warning("Read failed for %s: %s", path, exc)
        return ""


def _domain_for_doc_path(path: str, fallback: str = "coherence") -> str:
    s = path.lower()
    if "patent" in s:
        return "patent"
    if any(k in s for k in ("security", "hive", "defense", "sentinel")):
        return "defense"
    if any(k in s for k in ("voice", "tts", "twilio")):
        return "voice"
    if any(k in s for k in ("family", "sanctuary", "coach", "eft", "ifs")):
        return "coaching"
    if any(k in s for k in ("billing", "pricing", "quickbooks", "stripe", "gkm")):
        return "business"
    if any(k in s for k in ("migration", "api", "router", "python", "code", "bridge")):
        return "coding"
    if any(k in s for k in ("crystal", "quantum", "noetic", "odpe", "sovereign")):
        return "coherence"
    return fallback


class BaseScanner:
    name = "BaseScanner"

    def __init__(self, workspace: Path, config: Dict[str, Any]) -> None:
        self.workspace = workspace
        self.config = config

    def scan(self) -> List[Chunk]:
        raise NotImplementedError


class SovereignRulesScanner(BaseScanner):
    name = "SovereignRulesScanner"

    def scan(self) -> List[Chunk]:
        chunks: List[Chunk] = []
        paths = self.config.get("paths", [])
        for rel in paths:
            p = Path(rel)
            path = p if p.is_absolute() else self.workspace / rel
            if path.is_dir():
                for f in sorted(path.rglob("*.mdc")):
                    text = _safe_read(f)
                    for section in _split_markdown_sections(text, min_len=100):
                        chunks.append(
                            Chunk(
                                text=section,
                                source_file=str(f),
                                scanner_name=self.name,
                                domain="coherence",
                            )
                        )
            elif path.is_file():
                text = _safe_read(path)
                for section in _split_markdown_sections(text, min_len=100):
                    chunks.append(
                        Chunk(
                            text=section,
                            source_file=str(path),
                            scanner_name=self.name,
                            domain="coherence",
                        )
                    )
        return chunks


class CursorRulesScanner(BaseScanner):
    name = "CursorRulesScanner"

    def scan(self) -> List[Chunk]:
        chunks: List[Chunk] = []
        for rel in self.config.get("paths", []):
            p = Path(rel)
            path = p if p.is_absolute() else self.workspace / rel
            if path.is_dir():
                for f in sorted(path.rglob("*.mdc")):
                    text = _safe_read(f)
                    for section in _split_markdown_sections(text, min_len=80):
                        chunks.append(
                            Chunk(
                                text=section,
                                source_file=str(f),
                                scanner_name=self.name,
                                domain="coding",
                            )
                        )
            elif path.is_file():
                text = _safe_read(path)
                for section in _split_markdown_sections(text, min_len=80):
                    chunks.append(
                        Chunk(
                            text=section,
                            source_file=str(path),
                            scanner_name=self.name,
                            domain="coding",
                        )
                    )
        return chunks


class NightSchoolScanner(BaseScanner):
    name = "NightSchoolScanner"

    _modality_pattern = re.compile(
        r"MODALITY_KEYWORDS\s*=\s*\{(?P<body>.*?)\n\}", re.S
    )

    def scan(self) -> List[Chunk]:
        chunks: List[Chunk] = []
        for rel in self.config.get("paths", []):
            p = Path(rel)
            path = p if p.is_absolute() else self.workspace / rel
            if not path.exists():
                continue
            text = _safe_read(path)
            if not text:
                continue
            if path.name == "modality_selector.py":
                m = self._modality_pattern.search(text)
                if m:
                    body = m.group("body")
                    for line in body.splitlines():
                        line = line.strip().rstrip(",")
                        if not line or ":" not in line:
                            continue
                        chunks.append(
                            Chunk(
                                text=f"Night School modality map: {line}",
                                source_file=str(path),
                                scanner_name=self.name,
                                domain="clinical",
                                metadata={"source_type": "modality_keyword"},
                            )
                        )
            for section in _split_markdown_sections(text, min_len=80):
                chunks.append(
                    Chunk(
                        text=section,
                        source_file=str(path),
                        scanner_name=self.name,
                        domain="clinical",
                    )
                )
        return chunks


class BridgeTherapeuticPromptScanner(BaseScanner):
    name = "BridgeTherapeuticPromptScanner"

    _prompt_assign_pattern = re.compile(
        r"(?:^|\n)([A-Za-z_][A-Za-z0-9_]*?(?:SYSTEM_PROMPT|system_prompt|PROMPT|FRAMEWORK)[A-Za-z0-9_]*)\s*=\s*f?\"\"\"(.*?)\"\"\"",
        re.S,
    )

    def scan(self) -> List[Chunk]:
        chunks: List[Chunk] = []
        rel = self.config.get("path")
        if not rel:
            return chunks
        p = Path(rel)
        path = p if p.is_absolute() else self.workspace / rel
        text = _safe_read(path)
        if not text:
            return chunks
        lines = text.splitlines()

        ranges = self.config.get("prompt_line_ranges") or DEFAULT_BRIDGE_PROMPT_RANGES
        for idx, pair in enumerate(ranges):
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                continue
            start, end = int(pair[0]), int(pair[1])
            start_idx = max(0, start - 1)
            end_idx = min(len(lines), end)
            block = _clean_text("\n".join(lines[start_idx:end_idx]))
            for para in _split_paragraphs(block, min_len=120):
                chunks.append(
                    Chunk(
                        text=para,
                        source_file=f"{path}:{start}-{end}",
                        scanner_name=self.name,
                        domain="clinical",
                        metadata={"source_type": "line_range", "range_index": idx},
                    )
                )

        for m in self._prompt_assign_pattern.finditer(text):
            name = m.group(1)
            body = _clean_text(m.group(2))
            for para in _split_paragraphs(body, min_len=120):
                chunks.append(
                    Chunk(
                        text=para,
                        source_file=str(path),
                        scanner_name=self.name,
                        domain="clinical",
                        metadata={"source_type": "prompt_constant", "prompt_name": name},
                    )
                )
        return chunks


class GitHistoryScanner(BaseScanner):
    name = "GitHistoryScanner"

    meaningful_patterns = [
        "fix:",
        "feat:",
        "critical",
        "architecture",
        "migration",
        "security",
        "patent",
        "crystal",
        "quantum",
        "sovereign",
        "voice",
        "family",
        "eft",
        "odpe",
        "nevedal",
        "helix",
    ]
    skip_patterns = ["merge", "typo", "format", "lint", "bump", "deps"]

    def scan(self) -> List[Chunk]:
        chunks: List[Chunk] = []
        since = self.config.get("since", "6 months ago")
        max_commits = int(self.config.get("max_commits", 500))
        cmd = [
            "git",
            "-C",
            str(self.workspace),
            "log",
            f"--since={since}",
            f"--max-count={max_commits}",
            "--pretty=format:%H\t%ad\t%s",
            "--date=short",
        ]
        try:
            output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
        except Exception as exc:
            LOGGER.warning("GitHistoryScanner skipped: %s", exc)
            return chunks

        for row in output.splitlines():
            parts = row.split("\t", 2)
            if len(parts) != 3:
                continue
            commit, date_str, subject = parts
            subj_l = subject.lower()
            if any(s in subj_l for s in self.skip_patterns):
                continue
            if not any(p in subj_l for p in self.meaningful_patterns):
                continue
            files = self._files_changed(commit)
            domain = self._domain_from_files(files)
            text = (
                f"On {date_str}, commit {commit[:8]} recorded this decision: {subject}. "
                f"It affected files: {', '.join(files[:8]) if files else 'unknown files'}. "
                "This change captures implementation rationale and system behavior impact."
            )
            chunks.append(
                Chunk(
                    text=text,
                    source_file=f"git:{commit}",
                    scanner_name=self.name,
                    domain=domain,
                    metadata={"commit": commit, "date": date_str, "files": files},
                )
            )
        return chunks

    def _files_changed(self, commit: str) -> List[str]:
        cmd = ["git", "-C", str(self.workspace), "show", "--name-only", "--pretty=format:", commit]
        try:
            out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
            return [line.strip() for line in out.splitlines() if line.strip()][:30]
        except Exception:
            return []

    @staticmethod
    def _domain_from_files(files: Sequence[str]) -> str:
        joined = " ".join(files).lower()
        return _domain_for_doc_path(joined, fallback="coding")


class DocumentationScanner(BaseScanner):
    name = "DocumentationScanner"

    def scan(self) -> List[Chunk]:
        chunks: List[Chunk] = []
        for rel in self.config.get("paths", []):
            if rel == "*.md":
                files = sorted(self.workspace.glob("*.md"))
            else:
                p = Path(rel)
                path = p if p.is_absolute() else self.workspace / rel
                if path.is_dir():
                    files = sorted(path.rglob("*.md"))
                elif path.is_file():
                    files = [path]
                else:
                    files = []
            for file_path in files:
                text = _safe_read(file_path)
                domain = _domain_for_doc_path(str(file_path), fallback=self.config.get("domain", "coherence"))
                for section in _split_markdown_sections(text, min_len=80):
                    chunks.append(
                        Chunk(
                            text=section,
                            source_file=str(file_path),
                            scanner_name=self.name,
                            domain=domain,
                        )
                    )
        return chunks


class SessionOutputScanner(BaseScanner):
    name = "SessionOutputScanner"

    def scan(self) -> List[Chunk]:
        chunks: List[Chunk] = []
        p = Path(self.config.get("path", ""))
        base = p if p.is_absolute() else self.workspace / p
        if not base.exists():
            return chunks
        patterns = self.config.get("patterns", [])
        for pattern in patterns:
            matches = list(base.glob(pattern))
            for file_path in matches:
                text = self._extract_text(file_path)
                if not text:
                    continue
                domain = self.config.get("domain", _domain_for_doc_path(str(file_path), "coherence"))
                for section in _split_markdown_sections(text, min_len=80):
                    chunks.append(
                        Chunk(
                            text=section,
                            source_file=str(file_path),
                            scanner_name=self.name,
                            domain=domain,
                        )
                    )
        return chunks

    def _extract_text(self, file_path: Path) -> str:
        suffix = file_path.suffix.lower()
        if suffix in {".md", ".txt", ".py", ".json", ".yaml", ".yml"}:
            return _safe_read(file_path)
        if suffix == ".docx":
            try:
                from docx import Document

                doc = Document(str(file_path))
                return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            except Exception as exc:
                LOGGER.warning("DOCX parse failed for %s: %s", file_path, exc)
                return ""
        return ""


class OllamaFilter:
    def __init__(self, ollama_url: str, coding_model: str, clinical_model: str, default_model: str):
        self.ollama_url = ollama_url.rstrip("/")
        self.coding_model = coding_model
        self.clinical_model = clinical_model
        self.default_model = default_model

    def _select_model(self, domain: str) -> str:
        d = (domain or "").lower()
        if d in {"coding", "defense"}:
            return self.coding_model
        if d in {"clinical", "coherence", "coaching", "voice", "business", "culture", "patent", "general"}:
            return self.clinical_model
        return self.default_model

    async def evaluate(self, session: aiohttp.ClientSession, chunk: Chunk, model_override: Optional[str] = None) -> Dict[str, Any]:
        model = model_override or self._select_model(chunk.domain)
        # Keep inference bounded for very large sections while preserving semantics.
        bounded_chunk = chunk.text[:3500]
        base_prompt = get_filter_prompt(chunk.scanner_name, chunk.domain)
        prompt = base_prompt + f"\n\nTEXT CHUNK:\n{bounded_chunk}"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 220},
        }
        url = f"{self.ollama_url}/api/generate"

        try:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=180)) as resp:
                data = await resp.json(content_type=None)
        except Exception as exc:
            return {"pass": False, "reason": f"ollama_error: {exc}", "model": model}

        raw = str(data.get("response", "")).strip()
        if not raw:
            return {"pass": False, "reason": "empty_response", "model": model}

        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        decision = lines[0].upper() if lines else "FAIL"
        if decision != "PASS":
            reason = next((ln.split(":", 1)[1].strip() for ln in lines if ln.upper().startswith("REASON:")), "filtered_out")
            return {"pass": False, "reason": reason, "model": model}

        domain = next((ln.split(":", 1)[1].strip().lower() for ln in lines if ln.upper().startswith("DOMAIN:")), chunk.domain)
        if domain not in ALLOWED_DOMAINS:
            domain = chunk.domain if chunk.domain in ALLOWED_DOMAINS else "general"

        crystal_text = next((ln.split(":", 1)[1].strip() for ln in lines if ln.upper().startswith("CRYSTAL:")), "")
        if not crystal_text:
            remainder = "\n".join(lines[1:]).strip()
            crystal_text = remainder[:1200]
        crystal_text = _clean_text(crystal_text)
        if len(crystal_text) < 40:
            return {"pass": False, "reason": "crystal_too_short", "model": model}

        return {
            "pass": True,
            "model": model,
            "domain": domain,
            "crystal_text": crystal_text,
        }


class BluePusher:
    def __init__(self, push_url: str, token_env: str, fallback_path: Path):
        self.push_url = push_url
        self.token_env = token_env
        self.fallback_path = fallback_path

    def _headers(self) -> Dict[str, str]:
        token = os.getenv(self.token_env, "").strip()
        if not token:
            raise RuntimeError(f"Missing required env var: {self.token_env}")
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def push_batch(
        self,
        session: aiohttp.ClientSession,
        crystals: List[Dict[str, Any]],
        node_id: str,
        node_total: int,
    ) -> bool:
        body = {
            "node_id": node_id,
            "node_total": node_total,
            "crystals": crystals,
        }
        try:
            async with session.post(
                self.push_url,
                json=body,
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                text = await resp.text()
                if resp.status >= 300:
                    LOGGER.warning("Push failed [%s]: %s", resp.status, text)
                    self._append_fallback(crystals)
                    return False
                LOGGER.info("Push OK [%s]: %s", resp.status, text[:200])
                return True
        except Exception as exc:
            LOGGER.warning("Push exception: %s", exc)
            self._append_fallback(crystals)
            return False

    def _append_fallback(self, crystals: List[Dict[str, Any]]) -> None:
        self.fallback_path.parent.mkdir(parents=True, exist_ok=True)
        with self.fallback_path.open("a", encoding="utf-8") as f:
            for c in crystals:
                f.write(json.dumps(c, ensure_ascii=True) + "\n")


class BlueHarvester:
    def __init__(self, config: Dict[str, Any], args: argparse.Namespace) -> None:
        self.config = config
        self.args = args
        workspace = Path(config["blue_node"]["workspace"]).expanduser().resolve()
        scanners_cfg = config.get("scanners", {})
        self.scanners = {
            "SovereignRulesScanner": SovereignRulesScanner(workspace, scanners_cfg.get("sovereign_rules", {})),
            "CursorRulesScanner": CursorRulesScanner(workspace, scanners_cfg.get("cursor_rules", {})),
            "NightSchoolScanner": NightSchoolScanner(workspace, scanners_cfg.get("night_school", {})),
            "BridgeTherapeuticPromptScanner": BridgeTherapeuticPromptScanner(
                workspace, scanners_cfg.get("bridge_therapeutic_prompts", {})
            ),
            "GitHistoryScanner": GitHistoryScanner(workspace, scanners_cfg.get("git_history", {})),
            "DocumentationScanner": DocumentationScanner(workspace, scanners_cfg.get("documentation", {})),
            "SessionOutputScanner": SessionOutputScanner(workspace, scanners_cfg.get("session_outputs", {})),
        }
        models = config["blue_node"].get("models", {})
        self.filter = OllamaFilter(
            ollama_url=config["blue_node"].get("ollama_url", "http://localhost:11434"),
            coding_model=models.get("coding", "qwen2.5-coder:14b"),
            clinical_model=models.get("clinical", "qwen2.5:14b-instruct-q4_K_M"),
            default_model=models.get("default", "qwen2.5:14b-instruct-q4_K_M"),
        )
        fallback = Path(config["blue_node"].get("jsonl_fallback", "./data/blue_fallback.jsonl"))
        self.pusher = BluePusher(
            push_url=config["blue_node"]["green_push_url"],
            token_env=config.get("green_auth", {}).get("api_key_env", "SKYEYE_AUDIT_TOKEN"),
            fallback_path=fallback,
        )
        self.rate_limit = int(args.rate_limit or config["blue_node"].get("rate_limit_seconds", 10))
        self.initial_confidence = float(config["blue_node"].get("initial_confidence", 0.60))
        self.stats: Dict[str, int] = {
            "scanned": 0,
            "deduped": 0,
            "passed": 0,
            "failed": 0,
            "pushed": 0,
            "errors": 0,
        }

    def _scanner_names_to_run(self) -> List[str]:
        if self.args.scanner:
            return [self.args.scanner]
        return list(self.scanners.keys())

    def _collect_chunks(self) -> List[Chunk]:
        all_chunks: List[Chunk] = []
        for name in self._scanner_names_to_run():
            scanner = self.scanners.get(name)
            if not scanner:
                LOGGER.warning("Unknown scanner skipped: %s", name)
                continue
            chunks = scanner.scan()
            LOGGER.info("%s produced %d chunks", name, len(chunks))
            all_chunks.extend(chunks)
        return all_chunks

    @staticmethod
    def _chunk_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

    def _dedupe_chunks(self, chunks: Iterable[Chunk]) -> List[Chunk]:
        seen: set[str] = set()
        out: List[Chunk] = []
        for chunk in chunks:
            h = self._chunk_hash(chunk.text)
            if h in seen:
                self.stats["deduped"] += 1
                continue
            seen.add(h)
            out.append(chunk)
        return out

    async def run(self) -> int:
        chunks = self._collect_chunks()
        unique_chunks = self._dedupe_chunks(chunks)
        if self.args.max_chunks and self.args.max_chunks > 0:
            unique_chunks = unique_chunks[: self.args.max_chunks]
            LOGGER.info("Applying max_chunks=%d for this run", self.args.max_chunks)
        LOGGER.info("Total unique chunks: %d", len(unique_chunks))

        if not unique_chunks:
            self._print_report()
            return 0

        node_id = f"blue_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        pushed_payload: List[Dict[str, Any]] = []

        _current_scanner = ""
        _current_file = ""
        _filter_times: List[float] = []

        async with aiohttp.ClientSession() as session:
            await report_heartbeat(session, status="running",
                                   chunks_total=len(unique_chunks),
                                   current_scanner="starting")

            total = len(unique_chunks)
            for idx, chunk in enumerate(unique_chunks, start=1):
                self.stats["scanned"] += 1
                _current_scanner = chunk.scanner_name
                _current_file = Path(chunk.source_file).name if "/" in chunk.source_file else chunk.source_file
                LOGGER.info("[%d/%d] Filtering %s chunk from %s (%d chars)...",
                            idx, total, chunk.scanner_name, _current_file, len(chunk.text))

                import time as _time
                _t0 = _time.monotonic()
                result = await self.filter.evaluate(session, chunk, model_override=self.args.model)
                _filter_times.append((_time.monotonic() - _t0) * 1000)

                LOGGER.info("[%d/%d] Result: %s (model=%s)",
                            idx, total,
                            "PASS" if result.get("pass") else f"FAIL ({result.get('reason', '?')})",
                            result.get("model", "?"))
                if not result.get("pass"):
                    self.stats["failed"] += 1
                    LOGGER.debug("Filter FAIL [%s] %s", chunk.scanner_name, result.get("reason"))
                else:
                    self.stats["passed"] += 1

                if idx % 25 == 0:
                    _scanned = max(self.stats["scanned"], 1)
                    await report_heartbeat(
                        session, status="running",
                        chunks_processed=self.stats["scanned"],
                        chunks_total=total,
                        chunks_passed=self.stats["passed"],
                        pass_rate=self.stats["passed"] / _scanned,
                        current_scanner=_current_scanner,
                        current_file=_current_file,
                        crystals_forged=self.stats["pushed"],
                        avg_filter_time_ms=sum(_filter_times[-25:]) / min(len(_filter_times), 25),
                    )

                if not result.get("pass"):
                    continue

                crystal_text = result["crystal_text"]
                content_hash = self._chunk_hash(crystal_text)
                payload = {
                    "crystal_text": crystal_text,
                    "domain": result.get("domain", chunk.domain),
                    "scope": "global",
                    "topics": [],
                    "source_count": 1,
                    "confidence": self.initial_confidence,
                    "content_hash": content_hash,
                    "face_path": "factory:mac-blue",
                    "origin_surface": "blue_harvest",
                    "context_start": None,
                    "context_end": None,
                    "source": "blue_harvest",
                    "metadata": {
                        "scanner": chunk.scanner_name,
                        "source_file": chunk.source_file,
                        "domain_hint": chunk.domain,
                        **chunk.metadata,
                    },
                }

                if self.args.dry_run:
                    self.stats["pushed"] += 1
                else:
                    pushed_payload.append(payload)
                    if len(pushed_payload) >= 20:
                        ok = await self.pusher.push_batch(session, pushed_payload, node_id, idx)
                        if ok:
                            self.stats["pushed"] += len(pushed_payload)
                        else:
                            self.stats["errors"] += len(pushed_payload)
                        pushed_payload = []

                await asyncio.sleep(self.rate_limit)

            if not self.args.dry_run and pushed_payload:
                ok = await self.pusher.push_batch(session, pushed_payload, node_id, len(unique_chunks))
                if ok:
                    self.stats["pushed"] += len(pushed_payload)
                else:
                    self.stats["errors"] += len(pushed_payload)

            _final_scanned = max(self.stats["scanned"], 1)
            await report_heartbeat(
                session, status="idle",
                chunks_processed=self.stats["scanned"],
                chunks_total=total,
                chunks_passed=self.stats["passed"],
                pass_rate=self.stats["passed"] / _final_scanned,
                current_scanner="complete",
                crystals_forged=self.stats["pushed"],
                avg_filter_time_ms=sum(_filter_times) / max(len(_filter_times), 1),
            )

        self._print_report()
        return 0 if self.stats["errors"] == 0 else 1

    def _print_report(self) -> None:
        scanned = max(self.stats["scanned"], 1)
        LOGGER.info(
            "\n[BLUE HARVEST REPORT]\n"
            "  scanned: %d\n"
            "  deduped: %d\n"
            "  passed:  %d (%.0f%%)\n"
            "  failed:  %d\n"
            "  pushed:  %d\n"
            "  errors:  %d\n",
            self.stats["scanned"],
            self.stats["deduped"],
            self.stats["passed"],
            (self.stats["passed"] / scanned) * 100,
            self.stats["failed"],
            self.stats["pushed"],
            self.stats["errors"],
        )


def load_config(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BLUE node local harvester")
    parser.add_argument("--config", default="backend/blue_harvester_config.yaml", help="Path to config file")
    parser.add_argument("--all", action="store_true", help="Run all scanners (default)")
    parser.add_argument("--scanner", help="Run one scanner by class name")
    parser.add_argument("--since", help="Override git since window (e.g. 7 days ago)")
    parser.add_argument("--dry-run", action="store_true", help="Run filter only, do not push")
    parser.add_argument("--model", help="Override all model routing with one model")
    parser.add_argument("--rate-limit", type=int, help="Seconds between chunk evaluations")
    parser.add_argument("--max-chunks", type=int, help="Optional cap on number of unique chunks to process")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    return parser.parse_args()


async def _async_main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config_path = Path(args.config)
    cfg = load_config(config_path)

    if args.since:
        cfg.setdefault("scanners", {}).setdefault("git_history", {})["since"] = args.since

    harvester = BlueHarvester(cfg, args)
    return await harvester.run()


def main() -> int:
    try:
        return asyncio.run(_async_main())
    except KeyboardInterrupt:
        LOGGER.warning("Interrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
