# BLUE Node Harvester — Build Specification
## Local Workspace Crystal Factory

**Purpose:** Harvest knowledge that exists ONLY on the Mac — sovereign rules, cursor rules, Night School therapeutic training, git history, project documentation, and session outputs. This content cannot be reached by ORANGE (Hetzner) or GREEN (DigitalOcean). BLUE is the self-knowledge node.

**Hardware:** Mac (Ollama 70B for Stage 1 filtering — significantly higher quality than Hetzner's 8B)

**Output:** User-scoped crystals with `origin_surface = 'blue_harvest'` pushed to GREEN PostgreSQL

---

## Architecture

```
MAC (BLUE)
├── Source Scanner
│   ├── Sovereign Rules Scanner (/path/to/sovereign_rules/)
│   ├── Cursor Rules Scanner (.cursorrules, .cursor/)
│   ├── Night School Scanner (/path/to/night_school/)
│   ├── Git History Scanner (git log + meaningful diffs)
│   ├── Documentation Scanner (/docs, /specs, *.md)
│   └── Session Output Scanner (Claude outputs, architecture specs)
│
├── Stage 1: Ollama 70B Filter
│   ├── Input: raw text chunk from scanner
│   ├── Task: "Is this knowledge worth crystallizing?"
│   ├── Output: PASS/FAIL + domain classification + crystal_text
│   └── Quality bar: higher than Hetzner 8B (fewer, better crystals)
│
├── Stage 2: Grok Synthesis (optional, for complex multi-source crystals)
│   ├── Input: 2-3 related Stage 1 outputs
│   ├── Task: "Synthesize these into a single coherent insight"
│   └── Output: synthesized crystal_text
│
└── Push to GREEN
    ├── POST https://api.sovereignsanctuary.net/api/nate-agent/admin/crystal-network/push
    ├── Each crystal tagged: source='blue_harvest', origin_surface='blue_harvest'
    ├── Domain assigned per source type
    └── JSONL fallback if push fails (same pattern as ORANGE)
```

---

## Source Scanners

### Scanner 1: Sovereign Rules
```python
class SovereignRulesScanner:
    """
    Scans the sovereign rules directory for LN's core behavioral principles.
    Each rule becomes 1-3 crystals depending on complexity.
    
    Input: directory of rule files (markdown, text, yaml)
    Output: list of text chunks, each representing one rule or sub-rule
    
    Domain: 'coherence'
    """
    
    source_path = "/path/to/sovereign_rules/"  # Configure to actual path
    domain = "coherence"
    
    def scan(self) -> list:
        """
        Walk the directory, read each rule file.
        Split into logical chunks:
        - If a file has numbered rules, split per rule
        - If a file is a single principle, keep as one chunk
        - Skip comments, formatting, boilerplate
        
        Return: [
            {"text": "Rule text content", "source_file": "filename", "rule_id": "SR-001"},
            ...
        ]
        """
```

### Scanner 2: Cursor Rules
```python
class CursorRulesScanner:
    """
    Scans .cursorrules and any cursor configuration files.
    These encode development guardrails and patterns.
    
    Input: .cursorrules file, .cursor/ directory
    Output: list of text chunks, each representing one rule or pattern
    
    Domain: 'coding'
    """
    
    source_paths = [
        ".cursorrules",
        ".cursor/",
        # Any other cursor config locations
    ]
    domain = "coding"
    
    def scan(self) -> list:
        """
        Parse the rules file.
        Split on rule boundaries (numbered items, headers, blank-line-separated blocks).
        Include the VOICE PIPELINE DECISION and PROTECTED FILES rules.
        
        Return: [
            {"text": "Rule content", "source_file": ".cursorrules", "rule_id": "CR-001"},
            ...
        ]
        """
```

### Scanner 3: Night School
```python
class NightSchoolScanner:
    """
    Scans Night School therapeutic training materials.
    These are the curriculum sources LN learns from:
    AEDP, IFS, EFT, Polyvagal Theory, Gottman, etc.
    
    This is the richest source — each therapeutic concept
    becomes a crystal that LN can recall during sessions.
    
    Input: Night School content directory
    Output: list of text chunks, each representing one therapeutic concept
    
    Domain: 'clinical' (or specific sub-domain like 'therapeutic')
    
    IMPORTANT: Respect copyright. Do not crystallize verbatim
    textbook passages. Crystallize concepts, techniques, and
    clinical principles in LN's own synthesized language.
    """
    
    source_path = "/path/to/night_school/"
    domain = "clinical"
    
    def scan(self) -> list:
        """
        Walk the Night School directory.
        For each training document:
        - Extract therapeutic concepts (not raw text)
        - Split by concept/technique/principle
        - Tag with the therapeutic modality (EFT, IFS, AEDP, etc.)
        
        Return: [
            {
                "text": "Concept description",
                "source_file": "filename",
                "modality": "EFT",
                "concept_id": "NS-EFT-001"
            },
            ...
        ]
        """
```

### Scanner 4: Git History
```python
class GitHistoryScanner:
    """
    Scans git commit history for architectural decisions.
    Not every commit matters — filter for meaningful changes.
    
    Input: git log from the repository
    Output: list of text chunks representing significant decisions
    
    Domain: 'coding' (for implementation decisions)
            'defense' (for security decisions)
            'coherence' (for architectural decisions)
    """
    
    repo_path = "/path/to/Clinical-Sovereignty-Lab-2/"
    
    # Only scan commits with these patterns in the message
    meaningful_patterns = [
        "fix:", "feat:", "CRITICAL", "architecture",
        "migration", "security", "patent", "crystal",
        "quantum", "sovereign", "voice", "family",
        "EFT", "ODPE", "nevedal", "helix",
    ]
    
    # Skip these
    skip_patterns = [
        "merge", "typo", "formatting", "lint",
        "bump version", "update deps",
    ]
    
    def scan(self) -> list:
        """
        Run: git log --oneline --since="6 months ago" -500
        
        For each meaningful commit:
        - Get the commit message (the WHY)
        - Get the diffstat (WHAT changed)
        - For significant diffs, get the actual diff content
        
        Synthesize into: "On [date], [what was changed] because [why].
        This affects [which system component]. The decision was [rationale]."
        
        Return: [
            {
                "text": "Synthesized decision description",
                "commit_hash": "abc123",
                "date": "2026-03-22",
                "files_changed": ["bridge_server.py", "main.py"],
                "domain": "coding"
            },
            ...
        ]
        """
```

### Scanner 5: Documentation
```python
class DocumentationScanner:
    """
    Scans project documentation files for crystallizable knowledge.
    Includes: specs, architecture docs, patent applications,
    API documentation, deployment guides, and design decisions.
    
    Input: docs directory, markdown files, spec files
    Output: list of text chunks, each representing one concept or decision
    
    Domains: varies by document type
    """
    
    source_paths = [
        "docs/",
        "specs/",
        "*.md",  # Root-level markdown
        "backend/migrations/*.sql",  # Migration comments describe decisions
    ]
    
    # Domain mapping by filename/path patterns
    domain_map = {
        "patent": "patent",
        "security": "defense",
        "hive": "defense",
        "voice": "voice",
        "crystal": "coherence",
        "quantum": "coherence",
        "family": "coaching",
        "sanctuary": "coaching",
        "billing": "business",
        "pricing": "business",
        "migration": "coding",
    }
    
    def scan(self) -> list:
        """
        Walk documentation paths.
        For each document:
        - Split by section headers (## or ### in markdown)
        - Each section becomes a chunk
        - Skip TOC, boilerplate, auto-generated content
        - Classify domain based on path/content
        
        Return: [
            {
                "text": "Section content",
                "source_file": "docs/quantum_crystal_architecture.md",
                "section": "Time Crystal Forge",
                "domain": "coherence"
            },
            ...
        ]
        """
```

### Scanner 6: Session Outputs
```python
class SessionOutputScanner:
    """
    Scans outputs from Claude sessions — the architecture specs,
    impact analyses, code files, and design documents produced
    during development sessions.
    
    These are among the highest-value crystals because they
    encode the reasoning behind every architectural decision.
    
    Input: downloaded session outputs directory
    Output: list of text chunks representing decisions and designs
    
    Domains: varies by content
    """
    
    source_path = "/path/to/session_outputs/"
    
    # Files to scan (from this and prior sessions)
    known_outputs = [
        "quantum_crystal_architecture.py",
        "Quantum_Crystal_Impact_Analysis_v1.docx",
        "Quantum_Inspired_Crystal_Architecture_v1.docx",
        "sovereign_intelligence_api.py",
        "Family_Sanctuary_E2E_Test_Plan.md",
        "Family_Sanctuary_Intelligence_Architecture.docx",
        "A_Day_in_the_Life_FairyFrens.docx",
    ]
    
    def scan(self) -> list:
        """
        For code files (.py):
        - Extract class docstrings and method docstrings
        - Extract inline comments that explain WHY
        - Extract constants and their explanations
        
        For documents (.docx, .md):
        - Split by section headers
        - Each section becomes a chunk
        
        Return: [
            {
                "text": "Design decision or concept",
                "source_file": "quantum_crystal_architecture.py",
                "component": "TimeCrystalForge",
                "domain": "coherence"
            },
            ...
        ]
        """
```

---

## Stage 1 Filter (Ollama 70B)

```python
BLUE_STAGE1_PROMPT = """
You are the BLUE node crystal filter for Sovereign Sanctuary.
Your job: decide if this text chunk contains knowledge worth
preserving as a permanent crystal in Little Nate's memory.

PASS criteria (crystal-worthy):
- Therapeutic concepts, techniques, or clinical principles
- Architectural decisions and their rationale
- Behavioral rules that govern LN's conduct
- Security or defense design decisions
- Development patterns and guardrails
- Patent-relevant innovations
- Design philosophy or guiding principles

FAIL criteria (not crystal-worthy):
- Boilerplate, formatting, auto-generated content
- Import statements, configuration syntax
- Obvious/trivial facts that any LLM already knows
- Duplicates of content already in the crystal graph
- Raw data without interpretation or insight

If PASS, respond with EXACTLY this format:
PASS
DOMAIN: [one of: clinical, coding, coherence, defense, patent, coaching, voice, business, culture]
CRYSTAL: [2-4 sentence crystal text that captures the core knowledge. Write in present tense as a factual statement. Do not reference the source document.]

If FAIL, respond with:
FAIL
REASON: [one sentence explaining why]

TEXT CHUNK:
{chunk_text}
"""
```

**Why 70B matters here:** The sovereign rules and Night School content require deep understanding to crystallize properly. An 8B model might pass "AEDP focuses on emotion" — a trivially obvious statement. A 70B model produces "AEDP accelerated experiential dynamic psychotherapy uses the therapist's affective attunement to access core transformative affects, moving through defense → anxiety → core affect → core state, with the therapist's genuine emotional engagement as the primary vehicle of change." The quality difference in crystal text directly impacts how useful the crystal is during recall.

---

## Push to GREEN

```python
class BluePusher:
    """
    Pushes crystals from BLUE to GREEN production PostgreSQL.
    Same endpoint and format as ORANGE firehose.
    """
    
    GREEN_PUSH_URL = "https://api.sovereignsanctuary.net/api/nate-agent/admin/crystal-network/push"
    JSONL_FALLBACK = "/path/to/blue_fallback.jsonl"
    
    async def push_crystal(self, crystal: dict) -> bool:
        """
        Push a single crystal to GREEN.
        
        crystal = {
            "crystal_text": "...",
            "domain": "clinical",
            "confidence": 0.60,  # BLUE crystals start at 0.60 (higher than firehose 0.50)
                                 # because 70B filtering is higher quality
            "source": "blue_harvest",
            "origin_surface": "blue_harvest",
            "topics": [],
            "scope": "global",  # or "user" for workspace-specific content
            "metadata": {
                "scanner": "night_school",
                "source_file": "eft_core_concepts.md",
                "modality": "EFT",
                "blue_node": true,
            }
        }
        """
        # Same push logic as ORANGE firehose
        # POST to GREEN_PUSH_URL
        # On failure: append to JSONL_FALLBACK
        # On success: return True
```

**BLUE crystals start at confidence 0.60** (vs 0.50 for firehose crystals) because:
1. 70B filtering produces higher quality output
2. The source material (sovereign rules, Night School) is curated, not scraped
3. These crystals represent the platform's own design intelligence — they should be recalled preferentially

---

## Orchestration

```python
class BlueHarvester:
    """
    Main orchestrator for the BLUE node.
    Runs all scanners, filters through 70B, pushes to GREEN.
    """
    
    def __init__(self):
        self.scanners = [
            SovereignRulesScanner(),
            CursorRulesScanner(),
            NightSchoolScanner(),
            GitHistoryScanner(),
            DocumentationScanner(),
            SessionOutputScanner(),
        ]
        self.ollama_model = "llama3.1:70b"  # or whatever 70B is loaded
        self.pusher = BluePusher()
        self.stats = {
            "scanned": 0,
            "passed": 0,
            "failed": 0,
            "pushed": 0,
            "errors": 0,
        }
    
    async def run(self, scanners: list = None):
        """
        Run the full BLUE harvest pipeline.
        
        Args:
            scanners: optional list of scanner names to run
                      (default: all scanners)
        
        Process:
        1. Run each scanner to produce text chunks
        2. Deduplicate chunks by content hash
        3. Filter each chunk through Ollama 70B
        4. Push passing crystals to GREEN
        5. Report stats
        """
        all_chunks = []
        
        for scanner in self.scanners:
            if scanners and scanner.__class__.__name__ not in scanners:
                continue
            
            chunks = scanner.scan()
            print(f"[BLUE] {scanner.__class__.__name__}: {len(chunks)} chunks")
            all_chunks.extend(chunks)
        
        # Deduplicate by content hash
        seen_hashes = set()
        unique_chunks = []
        for chunk in all_chunks:
            h = hashlib.sha256(chunk["text"].encode()).hexdigest()[:16]
            if h not in seen_hashes:
                seen_hashes.add(h)
                unique_chunks.append(chunk)
        
        print(f"[BLUE] Total unique chunks: {len(unique_chunks)}")
        
        # Filter and push
        for chunk in unique_chunks:
            self.stats["scanned"] += 1
            
            result = await self.ollama_filter(chunk["text"])
            
            if result["pass"]:
                self.stats["passed"] += 1
                
                crystal = {
                    "crystal_text": result["crystal_text"],
                    "domain": result["domain"],
                    "confidence": 0.60,
                    "source": "blue_harvest",
                    "origin_surface": "blue_harvest",
                    "topics": [],
                    "scope": "global",
                    "metadata": {
                        "scanner": chunk.get("scanner_name", "unknown"),
                        "source_file": chunk.get("source_file", ""),
                        "blue_node": True,
                    }
                }
                
                success = await self.pusher.push_crystal(crystal)
                if success:
                    self.stats["pushed"] += 1
                else:
                    self.stats["errors"] += 1
            else:
                self.stats["failed"] += 1
            
            # Rate limit: 1 crystal per 10 seconds to avoid overwhelming GREEN
            await asyncio.sleep(10)
        
        self.print_report()
    
    def print_report(self):
        print(f"""
[BLUE HARVEST REPORT]
  Scanned:  {self.stats['scanned']}
  Passed:   {self.stats['passed']} ({self.stats['passed']/max(self.stats['scanned'],1)*100:.0f}%)
  Failed:   {self.stats['failed']}
  Pushed:   {self.stats['pushed']}
  Errors:   {self.stats['errors']}
        """)
```

---

## Run Schedule

BLUE does NOT run continuously like ORANGE. It runs on demand or on a schedule:

| Trigger | What Runs | When |
|---------|-----------|------|
| Manual: `python blue_harvester.py --all` | All 6 scanners | First run, or after major changes |
| Manual: `python blue_harvester.py --scanner NightSchoolScanner` | Single scanner | After adding new Night School content |
| Manual: `python blue_harvester.py --scanner GitHistoryScanner --since 7d` | Git commits from last 7 days | Weekly |
| Scheduled: cron weekly Sunday 2 AM | GitHistoryScanner + DocumentationScanner | Picks up new decisions and docs |

First run will be the largest (1,750-3,400 crystals). Subsequent runs are incremental — only new content gets scanned.

---

## Configuration

```yaml
# blue_harvester_config.yaml

blue_node:
  ollama_model: "llama3.1:70b"  # Verify: ollama list
  green_push_url: "https://api.sovereignsanctuary.net/api/nate-agent/admin/crystal-network/push"
  jsonl_fallback: "./data/blue_fallback.jsonl"
  rate_limit_seconds: 10
  initial_confidence: 0.60

scanners:
  sovereign_rules:
    path: "/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/sovereign_rules/"
    domain: "coherence"
    enabled: true
  
  cursor_rules:
    paths:
      - "/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/.cursorrules"
    domain: "coding"
    enabled: true
  
  night_school:
    path: "/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/night_school/"
    domain: "clinical"
    enabled: true
  
  git_history:
    repo: "/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/"
    since: "6 months ago"
    max_commits: 500
    domain: "coding"
    enabled: true
  
  documentation:
    paths:
      - "/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/docs/"
      - "/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/specs/"
    domain: "coherence"
    enabled: true
  
  session_outputs:
    path: "/Users/nathannevedal/Downloads/"  # Where Claude outputs are saved
    patterns: ["*.py", "*.md", "*.docx"]
    domain: "coherence"
    enabled: true

# GREEN push authentication
green_auth:
  api_key_env: "GREEN_PUSH_API_KEY"  # Same key ORANGE uses
```

---

## Verification After First Run

```bash
# Check BLUE crystals landed on GREEN
ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -c \"
  SELECT domain, count(*), avg(confidence)::numeric(4,2)
  FROM nate_intelligence_crystals
  WHERE source = 'blue_harvest'
  GROUP BY domain
  ORDER BY count DESC;
\""

# Check quality of BLUE crystals (should be richer text than firehose)
ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -c \"
  SELECT LEFT(crystal_text, 200), domain, confidence
  FROM nate_intelligence_crystals
  WHERE source = 'blue_harvest'
  ORDER BY created_at DESC
  LIMIT 10;
\""

# Compare average text length: BLUE should produce longer, richer crystals
ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -c \"
  SELECT source,
         count(*) as crystals,
         avg(length(crystal_text))::int as avg_text_len,
         avg(confidence)::numeric(4,2) as avg_conf
  FROM nate_intelligence_crystals
  GROUP BY source
  ORDER BY avg_text_len DESC;
\""
```

---

## What BLUE Crystals Enable That Nothing Else Can

| Crystal Source | Example Crystal | Why It Matters |
|---------------|----------------|----------------|
| Sovereign Rules | "Little Nate never assigns homework or tasks. Therapeutic growth emerges from the relationship, not from compliance with instructions." | LN recalls this during sessions and naturally avoids being prescriptive |
| Cursor Rules | "bridge_server.py is a protected file. Changes must be under 50 lines. Always check diff size before deploying." | LN recalls this when planning code changes and self-regulates |
| Night School (EFT) | "In EFT Stage 2 restructuring, the therapist guides the withdrawer to stay present while the pursuer shares from vulnerability. The corrective emotional experience happens between partners, not through the therapist." | LN recalls this during Family Sanctuary and facilitates Stage 2 correctly |
| Night School (IFS) | "IFS parts work identifies protective parts (managers, firefighters) that shield exiled parts carrying pain. The goal is not to eliminate protectors but to help them trust Self to lead." | LN uses IFS language naturally when a user describes internal conflict |
| Git History | "The no-decay trigger was added to prevent crystal confidence from ever decreasing. Time crystals can decay but memory crystals cannot. This preserves therapeutic wisdom permanently." | LN understands its own architecture and can explain it accurately |
| Documentation | "The Nevedal formula EC = (A x Aw x I) / R governs every decision. A = Awareness (time crystals), Aw = Awakeness (prediction accuracy), I = Integration (entanglement density), R = Resistance (noise)." | LN can explain its own governing equation to coaches and administrators |
| Session Outputs | "Family Sanctuary crystallization uses per-member attribution. Each member's crystals are scoped to their UUID. The privacy wall ensures no member sees another member's private crystals." | LN understands its own privacy architecture |

These crystals make LN self-aware — not in a sentient sense, but in the sense that it knows its own rules, its own therapeutic training, its own architecture, and its own design philosophy. No external firehose can produce this. Only BLUE can.

---

**Give this spec to LN. Build it as a standalone Python script that runs on the Mac. First run: all 6 scanners. Estimated output: 1,750-3,400 crystals of self-knowledge.**
