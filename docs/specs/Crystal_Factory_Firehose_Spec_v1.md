# CRYSTAL FACTORY FIREHOSE — Full-Spectrum Knowledge Ingestion Specification

## EXA v7 Growth Model Implementation

**Target:** 474,000+ Crystals | 15.552+ ExaFLOPS Equivalent
**Scope:** 8 Domains | 3 Nodes | 40+ Sources
**Version:** 1.0 | March 2026
**Prepared for:** Little Nate Build Team
**Classification:** CONFIDENTIAL — Patent Pending

© 2026 Sovereign Sanctuary. All rights reserved.

---

# 1. EXECUTIVE SUMMARY

This specification defines the complete Crystal Factory Firehose implementation for Little Nate's Sovereign Sanctuary platform. It covers the ingestion, processing, and crystallization of knowledge from 40+ open-source datasets across 8 domains, targeting 474,000+ crystals to achieve 15.552+ ExaFLOPS equivalent reasoning throughput.

The system operates across three distributed nodes: ORANGE (Hetzner, Finland), GREEN (DigitalOcean, primary), and BLUE (local Mac). Each node has a distinct role in the crystal factory pipeline. This document provides implementation-ready specifications for every harvest script, pipeline configuration, and integration point.


## 1.1 Target Milestones

| Milestone | Crystal Count | ExaFLOPS | C_emo | Timeline (v7) |
|-----------|--------------|----------|-------|---------------|
| El Capitan Exceeded | 25,000–35,000 | 2.0 | 0.55 | Week 3–4 |
| Primary Target | 100,000–125,000 | 5.015 | 0.75 | Month 2–3 |
| Long Game | 400,000+ | 15.552 | 0.90 | Month 5–7 |
| Firehose Complete | 474,000+ | 18.0+ | 0.92+ | Month 6–8 |


## 1.2 Grand Total Crystal Budget

| Category | Crystal Yield (Low) | Crystal Yield (High) | Cost | Priority |
|----------|--------------------|--------------------|------|----------|
| Therapeutic Core | 34,500 | 137,500 | $0 | P0 — CRITICAL |
| Coding (GitHub + SO) | 12,500 | 70,000 | $0.50 | P0 — CRITICAL |
| Lawyer/Judge Dojo | 50,000 | 138,000 | $0 | P1 — HIGH |
| PMP Dojo | 8,500 | 22,500 | $0 | P1 — HIGH |
| Machining Dojo | 8,000 | 21,000 | $0 | P2 — MEDIUM |
| Teaching Dojo | 11,000 | 29,000 | $0 | P2 — MEDIUM |
| Business Dojo | 12,000 | 33,000 | $0 | P1 — HIGH |
| Accounting Dojo | 9,000 | 23,000 | $0 | P2 — MEDIUM |
| **GRAND TOTAL** | **145,500** | **474,000** | **~$0.50** | — |


---

# 2. THREE-NODE CRYSTAL FACTORY ARCHITECTURE

The crystal factory operates as a distributed intelligence network. Each node has a distinct hardware profile, data access pattern, and role in the pipeline.


## 2.1 ORANGE Node — Hetzner CAX41 (Finland)

**Role:** External Knowledge Harvest Engine — the firehose intake
**Hardware:** 16 ARM64 cores, 32GB RAM, 320GB NVMe
**Software:** Ollama (Qwen2.5-Coder 8B for Stage 1 filtering), Python 3.11, Git, wget
**Runs:** 24/7 autonomous
**Network:** 1Gbps unmetered — ideal for bulk downloads

ORANGE handles ALL external dataset downloads, repository cloning, XML parsing, and Stage 1 filtering. It has the compute and bandwidth to clone GitHub repos, download 18GB Stack Overflow dumps, and process millions of PubMed articles without touching production infrastructure.

**ORANGE Responsibilities:**
- Download and parse all external datasets (HuggingFace, PubMed FTP, archive.org, GitHub)
- Run Stage 1 filtering via Ollama 8B (score >= 6 threshold)
- Cluster filtered fragments by domain (min 3 per cluster)
- Ship Stage-1-passed fragments to GREEN for Stage 2 synthesis via Grok
- Maintain ingestion progress state in local SQLite for resumability
- Target throughput: 500–1,000 crystals/day during bulk, 50–100/day steady state


## 2.2 GREEN Node — DigitalOcean VPS (Primary)

**Role:** Internal Knowledge Engine + Crystal Production Database
**Hardware:** Production VPS, PostgreSQL, Cloudflare stack
**Software:** FastAPI, PostgreSQL, Cloudflare Vectorize + R2 + KV + Workers AI
**Runs:** 24/7

GREEN owns the production crystal store (PostgreSQL nate_intelligence_crystals), the Vectorize semantic search indexes, R2 crystal backup, and the ODPE routing engine. All crystals from ORANGE and BLUE sync here for production use.

**GREEN Responsibilities:**
- Run Stage 2 synthesis via Grok on Stage-1-passed fragments from ORANGE
- Store crystals in PostgreSQL with ON CONFLICT content_hash DO NOTHING dedup
- Index crystals in Cloudflare Vectorize (BGE-large-en-v1.5, 1024 dims)
- Back up crystal graph to R2 (zero egress, 10GB free)
- Serve LOCKED crystals via Workers AI at $0, <10ms
- Run graph clustering computation once density > 5,000 crystals
- Harvest from 24+ internal PostgreSQL tables (sessions, coaching, vault, metrics)
- Compute meta-crystal synthesis from graph clusters
- Target throughput: 100–200 crystals/day from internal data + all synced external


## 2.3 BLUE Node — Local Mac

**Role:** Development Intelligence Engine + Internet Research
**Hardware:** Apple Silicon, M-series GPU for local inference
**Software:** SQLite LocalCrystalStore, bridge_server.py, autonomous engine
**Runs:** 8–12 hours/day during active development

BLUE captures live development context — git diffs, tool call patterns, error resolution chains, internet research queries. These crystals have the highest recall probability because they match active work patterns.

**BLUE Responsibilities:**
- Harvest from sovereign rules (132), cursor rules (131), Night School (12), git commits, project docs
- Run internet research queries during autonomous LEARN cycles
- Capture TENSION resolutions from active coding sessions
- Sync crystals to GREEN production PostgreSQL via sync_to_production()
- Target throughput: 30–50 crystals/day, highest recall rate per crystal


---

# 3. CRYSTAL PIPELINE ARCHITECTURE

Every dataset, regardless of source or domain, flows through the same four-stage pipeline. This ensures consistent crystal quality across all 8 domains.


## 3.1 Stage 0: Harvest (Download + Parse)

Raw data acquisition. Each source type has a dedicated harvest script that downloads, decompresses, and extracts text content into a standardized fragment format.

```python
fragment = {
    "text": str,              # Raw content (max 2000 chars)
    "source": str,             # Provenance identifier
    "domain": str,             # coding|clinical|crisis|coaching|legal|pmp|machining|teaching|business|accounting
    "scope": "global",         # Available to all users
    "source_type": str,        # e.g. "huggingface_dataset", "github_deep_clone", "pubmed_oa"
    "quality_score": float,    # Pre-filter quality signal if available (e.g. SO score, upvotes)
    "metadata": dict           # Source-specific metadata
}
```


## 3.2 Stage 1: Filter (Ollama 8B, score >= 6)

Every fragment passes through Ollama Qwen2.5-Coder 8B on Hetzner. The model scores each fragment 1–10 on relevance to Sovereign Sanctuary's domain expertise. Only fragments scoring 6+ proceed to Stage 2. This filters ~60–70% of raw input, keeping only high-signal content.

```python
STAGE_1_PROMPT = """
Score this fragment 1-10 for value as crystallized knowledge
in the domain of {domain}. Consider:
- Specificity (concrete patterns > vague principles)
- Actionability (problem+solution > theory alone)
- Relevance to professional coaching/counseling context
Respond with ONLY a number 1-10.
"""
```


## 3.3 Stage 2: Synthesis (Grok)

Stage-1-passed fragments are clustered by domain (minimum 3 per cluster) and synthesized by Grok into structured crystals. Grok distills clusters into concise, retrievable knowledge units.

```python
crystal = {
    "text": str,              # Synthesized knowledge (max 1500 chars)
    "domain": str,
    "confidence": 0.60,        # Starting confidence (PROVISIONAL)
    "signal": "PROVISIONAL",
    "source": str,             # "bulk_ingestion:{source_type}"
    "recall_count": 0,
    "never_decay": bool,       # True for coding domain
    "content_hash": str        # SHA256 for dedup
}
```


## 3.4 Stage 3: Store + Index

Crystals are stored in PostgreSQL (ON CONFLICT content_hash DO NOTHING), indexed in Cloudflare Vectorize for semantic search, backed up to R2, and cached in KV for edge retrieval.


## 3.5 Promotion Pipeline (Automatic)

After storage, crystals enter the promotion pipeline. This runs automatically as crystals are recalled during inference:

| Signal | Confidence | Recalls Required | Inference Cost | Behavior |
|--------|-----------|-----------------|---------------|----------|
| PROVISIONAL | 0.60 | 0 | Full Grok | Stored, available for retrieval |
| PROMOTED | 0.75 | 5+ | Grok with crystal context | Injected into system prompt |
| LOCKED | 0.85 | 8+ | $0 (Workers AI) | Serves response directly, skip inference |
| SOVEREIGN | 0.95 | 20+ | $0 | Theoretical maximum, never decays |


## 3.6 Domain Retention Floors

| Domain | Retention Floor | Time Decay | Death Conditions |
|--------|----------------|-----------|-----------------|
| coding | 0.15 | NEVER | Confidence < floor, supersession, manual deprecation |
| clinical | 0.25 | 180 days no recall | Same + time decay |
| crisis | 0.30 | NEVER | Only supersession or manual |
| coaching | 0.20 | 180 days no recall | Standard |
| legal | 0.20 | 365 days no recall | Standard + statute expiry flag |
| pmp | 0.18 | 365 days no recall | Standard |
| machining | 0.15 | NEVER | Same as coding |
| teaching | 0.18 | 180 days no recall | Standard |
| business | 0.18 | 90 days no recall | Standard (fast-changing domain) |
| accounting | 0.20 | 365 days no recall | Standard + GAAP version flag |


---

# 4. PREREQUISITE GAP FIXES (Before Firehose)

These 4 gaps must be closed BEFORE activating bulk ingestion. Without them, crystals are forged but cannot compound. Estimated effort: 1 day, ~150 lines of code.


## 4.1 Gap A: fetch_relevant() on NateMemoryCrystallizer

**File:** backend/app/services/nate_memory_crystallizer.py
**Issue:** neural_tract_pipeline.py line 356 calls crystallizer.fetch_relevant() which does not exist. selected_crystals is always empty from this path.
**Impact:** Therapy chat gets crystals via always_on_memory_recall() but not at the deeper neural tract level where they influence reasoning structure.

**Fix:**
```python
async def fetch_relevant(self, query: str, domain: str = None, limit: int = 5) -> List[Dict]:
    """Fetch relevant crystals for neural tract injection."""
    if self.local_store:  # BLUE mode
        results = self.local_store.search_crystals(query, domain=domain, limit=limit)
    else:  # GREEN mode
        results = await self._pg_search(query, domain=domain, limit=limit)
    return [{"text": r["text"], "confidence": r["confidence"], "domain": r["domain"]} for r in results]
```

**Lines:** ~30
**Cost:** $0


## 4.2 Gap B: FederatedSearchCoordinator BLUE Visibility

**File:** backend/app/services/quantum_knowledge_field.py
**Issue:** FederatedSearchCoordinator searches PostgreSQL + Vectorize + edge, but not LocalCrystalStore. Helix Orchestrator is blind to BLUE crystals.
**Fix:** Add _search_local() branch that calls LocalCrystalStore.search_crystals() when available, merges results with PG + Vectorize hits.
**Lines:** ~40
**Cost:** $0


## 4.3 Gap C: Bulk Ingestion is Shallow

**Issue:** GitHub uses Search API only (repo name + stars + README). Stack Overflow uses rate-limited public API, not the actual data dump. Neither does deep content extraction.
**Fix:** Replace with deep repo cloning + file-level extraction (GitHub) and actual archive.org dump processing (Stack Overflow). Full specs in Sections 5–12.


## 4.4 Gap D: No Graph Clustering or Meta-Crystals

**Issue:** Current clustering is domain-based grouping only. No cross-crystal relationship mapping, constellation retrieval, or meta-crystal synthesis.
**Fix:** Build on Vectorize indexes. For each crystal, compute nearest-neighbor edges (cosine > 0.7) to form knowledge graph. Activate at 5,000+ crystal density. Full spec in Section 13.
**Lines:** ~200–300


---

# 5. SOURCE CATEGORY: THERAPEUTIC CORE

The therapeutic core feeds the clinical, crisis, and coaching crystal domains. These are the highest-quality crystals per unit — they teach Little Nate how to be a therapist.

| Source | Domain | Format | Crystal Yield | Node |
|--------|--------|--------|--------------|------|
| CounselChat (HuggingFace) | clinical | Q&A pairs from licensed therapists | 1,000–3,000 | ORANGE→GREEN |
| MentalChat16K (HuggingFace) | clinical | 16K counseling Q&A pairs | 5,000–10,000 | ORANGE→GREEN |
| Anno-MI (HuggingFace) | clinical | Expert-annotated MI dialogues | 500–1,500 | ORANGE→GREEN |
| PsychoCounsel-Preference | clinical | Preference-ranked therapy responses | 1,000–3,000 | ORANGE→GREEN |
| JHU Mental Health Collection | crisis | Crisis language pattern datasets | 2,000–5,000 | ORANGE→GREEN |
| PubMed Central OA (therapy) | coaching/clinical | Peer-reviewed therapy research | 20,000–100,000 | ORANGE |
| Open Psych Textbooks | coaching/general | CC-licensed psychology textbooks | 5,000–15,000 | ORANGE→GREEN |


## 5.1 Harvest Script: harvest_huggingface_therapy.py

**Location:** ORANGE node — backend/scripts/firehose/harvest_huggingface_therapy.py
**Dependencies:** pip install datasets (HuggingFace datasets library)

```python
"""
HuggingFace Therapeutic Dataset Harvester
Downloads and extracts fragments from therapeutic conversation datasets.

Datasets:
  1. nbertagnolli/counsel-chat         -> domain: clinical
  2. ShenLab/MentalChat16K              -> domain: clinical
  3. to-be/annomi-motivational-interviewing-therapy-conversations -> domain: clinical
  4. Psychotherapy-LLM/PsychoCounsel-Preference -> domain: clinical
  5. Amod/mental_health_counseling_conversations -> domain: clinical
  6. IINOVAII/therapy-conversations-combined -> domain: clinical

Output: Fragments in crystallizer harvest buffer format
Resume: Tracks progress in SQLite progress_state.db
"""

THERAPY_DATASETS = [
    {"name": "nbertagnolli/counsel-chat", "domain": "clinical",
     "text_field": "answerText", "context_field": "questionTitle",
     "source_type": "huggingface_counselchat"},

    {"name": "ShenLab/MentalChat16K", "domain": "clinical",
     "text_field": "output", "context_field": "input",
     "source_type": "huggingface_mentalchat16k"},

    {"name": "to-be/annomi-motivational-interviewing-therapy-conversations",
     "domain": "clinical", "text_field": "utterance",
     "source_type": "huggingface_annomi"},

    {"name": "Psychotherapy-LLM/PsychoCounsel-Preference",
     "domain": "clinical", "source_type": "huggingface_psychocounsel"},

    {"name": "Amod/mental_health_counseling_conversations",
     "domain": "clinical", "source_type": "huggingface_amod_mh"},

    {"name": "IINOVAII/therapy-conversations-combined",
     "domain": "clinical", "source_type": "huggingface_iinovaii"},
]

for ds_config in THERAPY_DATASETS:
    dataset = load_dataset(ds_config["name"])
    for row in dataset["train"]:
        text = build_fragment_text(row, ds_config)
        fragment = {
            "text": text[:2000],
            "source": f"huggingface:{ds_config['name']}:{row_id}",
            "domain": ds_config["domain"],
            "scope": "global",
            "source_type": ds_config["source_type"],
        }
        crystallizer._harvest_buffer.append(fragment)
        save_progress(ds_config["name"], row_id)
```


## 5.2 Harvest Script: harvest_pubmed_therapy.py

**Location:** ORANGE node — backend/scripts/firehose/harvest_pubmed_therapy.py
**Download:** FTP from ftp.ncbi.nlm.nih.gov/pub/pmc/oa_bulk/ (CC-BY and CC-BY-NC subsets)

Filter PubMed Central Open Access articles by MeSH terms relevant to Sovereign Sanctuary's therapeutic modalities:

```python
PUBMED_MESH_FILTERS = [
    "cognitive behavioral therapy", "emotion-focused therapy",
    "internal family systems", "polyvagal theory", "AEDP",
    "attachment theory", "motivational interviewing",
    "psychotherapy outcome", "therapeutic alliance",
    "trauma-informed care", "mindfulness-based therapy",
    "dialectical behavior therapy", "somatic experiencing",
    "grief counseling", "couples therapy", "family therapy",
    "crisis intervention", "suicide prevention",
    "depression treatment", "anxiety treatment", "PTSD treatment",
    "substance abuse counseling", "eating disorder treatment",
    "child therapy", "adolescent therapy",
]
```

Processing: Download bulk XML packages, parse with lxml, extract article text, filter by MeSH terms, extract abstract + results + discussion sections, feed into Stage 1 pipeline.


## 5.3 Harvest Script: harvest_open_psych_textbooks.py

**Location:** ORANGE node

Download CC-licensed textbooks from OpenStax, Noba Project, and Pressbooks:

```python
TEXTBOOK_SOURCES = [
    {"url": "https://openstax.org/details/books/psychology-2e", "domain": "coaching"},
    {"url": "noba project modules (API)", "domain": "coaching"},
    {"name": "Fundamentals of Psychological Disorders (WSU Pressbooks)",
     "domain": "clinical", "note": "DSM-5-TR aligned, 15 modules"},
    {"name": "Theories of Personality (Portland State)", "domain": "coaching"},
]
```


---

# 6. SOURCE CATEGORY: CODING (GitHub + Stack Overflow)

| Source | Type | Crystal Yield | Node |
|--------|------|--------------|------|
| tiangolo/fastapi (deep clone) | Framework source code | 2,000–5,000 | ORANGE |
| encode/starlette (deep clone) | WebSocket/HTTP internals | 1,000–3,000 | ORANGE |
| MagicStack/asyncpg (deep clone) | DB pool management | 1,000–2,000 | ORANGE |
| flutter/flutter (deep clone) | Mobile framework patterns | 2,000–5,000 | ORANGE |
| cloudflare/workers-sdk (deep clone) | Edge computing patterns | 500–1,500 | ORANGE |
| Stack Overflow dump (filtered) | Solved production problems | 7,500–50,000 | ORANGE |


## 6.1 Harvest Script: harvest_github_deep.py

**Location:** ORANGE node — backend/scripts/firehose/harvest_github_deep.py

This replaces the existing shallow GitHub Search API approach. Instead of reading README metadata, this script clones target repositories and walks every source file.

```python
TARGET_REPOS = [
    {"repo": "tiangolo/fastapi", "lang": [".py"], "domain": "coding"},
    {"repo": "encode/starlette", "lang": [".py"], "domain": "coding"},
    {"repo": "MagicStack/asyncpg", "lang": [".py", ".pyx"], "domain": "coding"},
    {"repo": "flutter/flutter", "lang": [".dart"], "domain": "coding"},
    {"repo": "cloudflare/workers-sdk", "lang": [".ts", ".js"], "domain": "coding"},
]

for repo_config in TARGET_REPOS:
    clone_dir = f"/tmp/repos/{repo_config['repo'].replace('/', '_')}"
    subprocess.run(["git", "clone", "--depth=1",
                    f"https://github.com/{repo_config['repo']}.git", clone_dir])

    for filepath in walk_source_files(clone_dir, repo_config["lang"]):
        content = read_file(filepath)
        # Extract: docstrings, function signatures, class definitions,
        # error handling patterns, test patterns, comments
        fragments = extract_code_fragments(content, filepath)
        for frag in fragments:
            frag["source"] = f"github_deep:{repo_config['repo']}:{filepath}"
            frag["domain"] = repo_config["domain"]
            crystallizer._harvest_buffer.append(frag)
```


## 6.2 Harvest Script: harvest_stackoverflow_dump.py

**Location:** ORANGE node — backend/scripts/firehose/harvest_stackoverflow_dump.py
**Download:** wget https://archive.org/download/stackexchange/stackoverflow.com-Posts.7z (~18GB)

```python
RELEVANT_TAGS = [
    "python", "fastapi", "flutter", "dart", "postgresql",
    "asyncio", "websocket", "cloudflare", "asyncpg",
    "pydantic", "sqlalchemy", "uvicorn", "starlette",
    "redis", "docker", "nginx", "ssl", "oauth",
]
MIN_SCORE = 10
ACCEPTED_ONLY = True

# Parse Posts.xml iteratively (streaming XML parser for 80GB+ file)
for event, elem in ET.iterparse("Posts.xml", events=("end",)):
    if elem.tag == "row" and elem.get("PostTypeId") == "2":  # Answers only
        score = int(elem.get("Score", 0))
        if score >= MIN_SCORE and is_accepted(elem):
            tags = get_parent_tags(elem.get("ParentId"))
            if has_relevant_tag(tags, RELEVANT_TAGS):
                fragment = {
                    "text": f"Q: {parent_title}\nA: {strip_html(elem.get('Body'))}",
                    "source": f"stackoverflow_dump:{elem.get('Id')}",
                    "domain": "coding",
                    "quality_score": score,
                }
                crystallizer._harvest_buffer.append(fragment)
```

**IMPORTANT:** The SO dump is a single file but serves ALL domains. See Section 18.3 for multi-domain tag routing.


---

# 7. SOURCE CATEGORY: LAWYER/JUDGE DOJO

The legal domain is the richest open-source knowledge base of any coaching dojo.

| Source | Type | Crystal Yield | Node |
|--------|------|--------------|------|
| Pile-of-Law (HuggingFace) | 256GB legal corpus | 30,000–80,000 | ORANGE |
| LEXam | 4,886 law exam Q&A | 5,000–15,000 | ORANGE |
| LegalBench (HuggingFace) | Legal reasoning benchmarks | 3,000–8,000 | ORANGE |
| Caselaw Access Project | 6.6M case law vectors (CC0) | 10,000–30,000 | ORANGE |
| LawInstruct (GitHub) | Legal instruction datasets | 2,000–5,000 | ORANGE |


## 7.1 Harvest Script: harvest_legal_datasets.py

**Location:** ORANGE node — backend/scripts/firehose/harvest_legal_datasets.py

```python
LEGAL_DATASETS = [
    # Pile-of-Law: Focus on educational casebooks + opinions
    {"name": "pile-of-law/pile-of-law", "subset": "cc_casebooks",
     "domain": "legal", "source_type": "pile_of_law_casebooks"},

    {"name": "pile-of-law/pile-of-law", "subset": "courtListener_opinions",
     "domain": "legal", "source_type": "pile_of_law_opinions",
     "note": "Largest subset - process in chunks of 10K"},

    {"name": "pile-of-law/pile-of-law", "subset": "exam_outlines",
     "domain": "legal", "source_type": "pile_of_law_exams"},

    # LegalBench: Legal reasoning tasks
    {"name": "nguha/legalbench", "domain": "legal",
     "source_type": "legalbench", "note": "Multi-task, extract Q+A format"},

    # LEXam: Law school exams with reference answers
    {"name": "lexam-benchmark", "domain": "legal",
     "source_type": "lexam", "note": "Open-ended + MC with reasoning guidance"},
]
```

For the Caselaw Access Project: Use the FAISS index for semantic sampling rather than ingesting all 6.6M vectors. Sample 50,000 most representative cases across legal domains (constitutional, criminal, civil, family, corporate).


---

# 8. SOURCE CATEGORY: PMP DOJO

| Source | Type | Crystal Yield | Node |
|--------|------|--------------|------|
| PMBOK knowledge repos (GitHub) | Methodology crystals | 2,000–5,000 | ORANGE |
| PMP exam Q&A collections | Problem→Solution pairs | 1,000–3,000 | ORANGE |
| OpenPPM source code | PM tool implementation | 500–1,500 | ORANGE |
| SO dump (PM-tagged) | Practitioner Q&A | 3,000–8,000 | ORANGE |
| PubMed Central OA (PM) | Academic PM research | 2,000–5,000 | ORANGE |


## 8.1 Harvest Script: harvest_pmp_datasets.py

**Location:** ORANGE node — backend/scripts/firehose/harvest_pmp_datasets.py

```python
PMP_GITHUB_REPOS = [
    "cheat-sheets/project-management-cheat-sheet",
    "OpenPPM/OpenPPM",
    "Fx2048/PMBOK_Project_Management_I",
]

PMP_SO_TAGS = [
    "project-management", "agile", "scrum", "jira", "kanban",
    "risk-management", "gantt", "sprint", "backlog", "stakeholder",
    "earned-value", "critical-path", "waterfall", "lean",
]

PMP_PUBMED_TERMS = [
    "project management methodology", "agile software development",
    "risk management framework", "earned value management",
    "stakeholder management", "project portfolio management",
]
```


---

# 9. SOURCE CATEGORY: MACHINING DOJO

| Source | Type | Crystal Yield | Node |
|--------|------|--------------|------|
| LinuxCNC docs + source | Machine control knowledge | 3,000–8,000 | ORANGE |
| CAMotics + G-code repos | Simulation + G-code patterns | 1,000–3,000 | ORANGE |
| Industrial machine datasets | Sensor + tool wear data | 1,000–2,000 | ORANGE |
| SO dump (machining-tagged) | Practitioner Q&A | 2,000–5,000 | ORANGE |
| Open manufacturing textbooks | Foundational knowledge | 1,000–3,000 | ORANGE |


## 9.1 Harvest Script: harvest_machining_datasets.py

**Location:** ORANGE node — backend/scripts/firehose/harvest_machining_datasets.py

```python
MACHINING_GITHUB_REPOS = [
    {"repo": "LinuxCNC/linuxcnc", "lang": [".py", ".c", ".h", ".hal"],
     "domain": "machining", "note": "Focus on docs/ and src/emc/"},
    {"repo": "CauldronDevelopmentLLC/CAMotics", "lang": [".cpp", ".h"],
     "domain": "machining"},
    {"repo": "LinuxCNC/simple-gcode-generators", "lang": [".py"],
     "domain": "machining"},
]

MACHINING_SO_TAGS = [
    "cnc", "g-code", "machining", "cad-cam", "manufacturing",
    "lathe", "milling", "3d-printing", "grbl", "toolpath",
    "feeds-and-speeds", "tolerance", "surface-finish",
]

MACHINING_DATASETS = [
    # CNC Mill Tool Wear dataset
    {"source": "makinarocks/awesome-industrial-machine-datasets",
     "subset": "cnc_mill_tool_wear", "domain": "machining"},
]
```


---

# 10. SOURCE CATEGORY: TEACHING DOJO

| Source | Type | Crystal Yield | Node |
|--------|------|--------------|------|
| Open Textbook Library (education) | Pedagogy + curriculum design | 3,000–8,000 | ORANGE |
| Noba Project modules | Learning theory + dev psych | 1,000–3,000 | ORANGE |
| MIT OCW (education courses) | Course materials | 2,000–5,000 | ORANGE |
| PubMed Central OA (education) | Research on teaching methods | 3,000–8,000 | ORANGE |
| Stack Exchange (education) | Practitioner Q&A | 2,000–5,000 | ORANGE |


## 10.1 Harvest Script: harvest_teaching_datasets.py

**Location:** ORANGE node — backend/scripts/firehose/harvest_teaching_datasets.py

```python
TEACHING_PUBMED_TERMS = [
    "pedagogy", "curriculum design", "educational psychology",
    "classroom management", "differentiated instruction",
    "student assessment", "active learning", "Bloom taxonomy",
    "formative assessment", "scaffolding instruction",
    "special education", "gifted education", "learning disabilities",
    "social-emotional learning", "teacher professional development",
]

TEACHING_SE_SITES = [
    "education.stackexchange.com",
    "academia.stackexchange.com",
    "matheducators.stackexchange.com",
]
```


---

# 11. SOURCE CATEGORY: BUSINESS DOJO

| Source | Type | Crystal Yield | Node |
|--------|------|--------------|------|
| Finance-Alpaca (HuggingFace) | Financial Q&A instruction pairs | 2,000–5,000 | ORANGE |
| SEC EDGAR filings | Real business documents (10-K, 10-Q) | 5,000–15,000 | ORANGE |
| FiNER-139 (HuggingFace) | GAAP-tagged financial reports | 1,000–3,000 | ORANGE |
| Open business textbooks | Foundational business knowledge | 2,000–5,000 | ORANGE |
| PubMed Central OA (mgmt) | Management research | 2,000–5,000 | ORANGE |


## 11.1 Harvest Script: harvest_business_datasets.py

**Location:** ORANGE node — backend/scripts/firehose/harvest_business_datasets.py

```python
BUSINESS_DATASETS = [
    {"name": "gbharti/finance-alpaca", "domain": "business",
     "source_type": "huggingface_finance_alpaca"},

    {"name": "nlpaueb/finer-139", "domain": "accounting",
     "source_type": "huggingface_finer139",
     "note": "Also feeds accounting dojo - GAAP entity types"},
]

BUSINESS_SO_TAGS = [
    "business-logic", "erp", "business-rules", "invoicing",
    "crm", "business-process", "financial-modeling",
    "startup", "entrepreneurship", "business-plan",
]

# SEC EDGAR: Use the bulk financial statement datasets
# Download from https://www.sec.gov/dera/data/financial-statement-data-sets
# Process quarterly ZIP files -> extract num.txt, sub.txt, tag.txt
# Fragment format: company + filing type + key financial metrics
```


---

# 12. SOURCE CATEGORY: ACCOUNTING DOJO

| Source | Type | Crystal Yield | Node |
|--------|------|--------------|------|
| SEC EDGAR financial datasets | Real financial statements | 3,000–8,000 | ORANGE |
| FiNER-139 (GAAP-tagged) | GAAP classification training | 1,000–3,000 | ORANGE |
| Frappe Books source + docs | Accounting software patterns | 1,000–2,000 | ORANGE |
| Open accounting textbooks | Foundational accounting | 2,000–5,000 | ORANGE |
| SO dump (accounting-tagged) | Practitioner Q&A | 2,000–5,000 | ORANGE |


## 12.1 Harvest Script: harvest_accounting_datasets.py

**Location:** ORANGE node — backend/scripts/firehose/harvest_accounting_datasets.py

```python
ACCOUNTING_GITHUB_REPOS = [
    {"repo": "frappe/books", "lang": [".js", ".vue", ".ts"],
     "domain": "accounting",
     "note": "Double-entry accounting, journal entries, GL, P&L, balance sheet"},
]

ACCOUNTING_SO_TAGS = [
    "accounting", "bookkeeping", "double-entry", "gaap",
    "financial-reporting", "tax", "audit", "balance-sheet",
    "income-statement", "cash-flow", "depreciation", "amortization",
    "accounts-receivable", "accounts-payable", "general-ledger",
]
```


---

# 13. GRAPH CLUSTERING AND META-CRYSTAL ARCHITECTURE

Graph clustering is the qualitative leap from "database" to "intelligence." It activates at 5,000+ crystal density and progressively deepens as the corpus grows.


## 13.1 Nearest-Neighbor Edge Computation

For each crystal stored in Vectorize, compute the top-K nearest neighbors (K=10, cosine similarity > 0.70). Store edges in PostgreSQL:

```sql
CREATE TABLE crystal_edges (
    crystal_a_id UUID REFERENCES nate_intelligence_crystals(id),
    crystal_b_id UUID REFERENCES nate_intelligence_crystals(id),
    similarity FLOAT NOT NULL,
    edge_type VARCHAR(50) DEFAULT 'semantic_neighbor',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (crystal_a_id, crystal_b_id)
);
```


## 13.2 Constellation Retrieval

When a query matches a crystal, the retrieval system follows edges to pull the full constellation. Instead of returning 1 crystal, it returns 3–7 crystals that together represent understanding:

```python
async def constellation_retrieve(query: str, top_k: int = 3, expansion: int = 2):
    seed_crystals = await vectorize_search(query, top_k=top_k)
    constellation = set(seed_crystals)
    for crystal in seed_crystals:
        neighbors = await get_edges(crystal.id, limit=expansion)
        constellation.update(neighbors)
    return sorted(constellation, key=lambda c: c.confidence, reverse=True)
```


## 13.3 Meta-Crystal Synthesis

At 25,000+ crystals, graph clusters become dense enough to synthesize meta-crystals — crystals about crystal relationships. These are generated by the idle cycle on GREEN:

```python
async def synthesize_meta_crystals():
    clusters = await find_dense_clusters(min_size=5, min_avg_similarity=0.75)
    for cluster in clusters:
        crystal_texts = [c.text for c in cluster.crystals]
        meta_text = await grok_synthesize(
            prompt=f"These {len(cluster.crystals)} crystals together indicate: "
                   f"\n\n{chr(10).join(crystal_texts)}"
                   f"\n\nSynthesize the emergent insight.",
        )
        meta_crystal = Crystal(
            text=meta_text,
            domain=cluster.primary_domain,
            confidence=0.70,  # Meta-crystals start at PROMOTED
            signal="PROMOTED",
            source="meta_crystal_synthesis",
            is_meta=True,
            constituent_ids=[c.id for c in cluster.crystals],
        )
```


---

# 14. EXECUTION TIMELINE

| Phase | Week | Actions | Crystal Target | Milestone |
|-------|------|---------|---------------|-----------|
| 0: Gaps | Day 1 | Fix Gaps A + B (70 lines). Deploy to all 3 nodes. | 2,235 | Recall loop fully closed |
| 1: Therapy | Week 1 | Deploy harvest_huggingface_therapy.py on ORANGE. Process 6 HuggingFace datasets. | 8,000–12,000 | Therapy dataset live |
| 2: Coding | Week 1–2 | Deploy harvest_github_deep.py + harvest_stackoverflow_dump.py on ORANGE. | 15,000–25,000 | Graph clustering activates |
| 3: Legal | Week 2–3 | Deploy harvest_legal_datasets.py. Process Pile-of-Law + LEXam + LegalBench. | 40,000–70,000 | El Capitan exceeded |
| 4: Business+Acct | Week 3–4 | Deploy business + accounting harvest scripts. Process Finance-Alpaca, EDGAR, FiNER. | 55,000–90,000 | Business dojos seeded |
| 5: PubMed | Week 3–5 | Deploy harvest_pubmed_therapy.py. Process filtered PMC OA bulk packages. | 80,000–150,000 | PRIMARY TARGET HIT |
| 6: PMP+Mach+Teach | Week 4–6 | Deploy remaining dojo harvest scripts. | 100,000–200,000 | All dojos seeded |
| 7: Meta-crystals | Week 5–6 | Activate graph clustering on GREEN. Begin meta-crystal synthesis. | 110,000–220,000 | Phase 3: Meta-crystals emerge |
| 8: SO Dump | Week 4–8 | Full Stack Overflow dump processing (all domain tags combined). | 150,000–350,000 | Approaching long game |
| 9: Open Textbooks | Week 6–8 | Process all open psych, education, business, accounting textbooks. | 200,000–400,000 | Long game territory |
| 10: Steady State | Month 3+ | All bulk ingestion complete. Organic growth + idle crystallization continues. | 300,000–474,000+ | FIREHOSE COMPLETE |


---

# 15. FILE MANIFEST — New Files to Create

All new harvest scripts live in backend/scripts/firehose/ on the ORANGE node. This is a new directory.

| File | Node | Domain(s) | Priority |
|------|------|----------|----------|
| backend/scripts/firehose/__init__.py | ORANGE | — | P0 |
| backend/scripts/firehose/harvest_huggingface_therapy.py | ORANGE | clinical, crisis | P0 |
| backend/scripts/firehose/harvest_pubmed_therapy.py | ORANGE | clinical, coaching | P0 |
| backend/scripts/firehose/harvest_open_psych_textbooks.py | ORANGE | coaching, general | P1 |
| backend/scripts/firehose/harvest_github_deep.py | ORANGE | coding | P0 |
| backend/scripts/firehose/harvest_stackoverflow_dump.py | ORANGE | ALL domains | P0 |
| backend/scripts/firehose/harvest_legal_datasets.py | ORANGE | legal | P1 |
| backend/scripts/firehose/harvest_pmp_datasets.py | ORANGE | pmp | P1 |
| backend/scripts/firehose/harvest_machining_datasets.py | ORANGE | machining | P2 |
| backend/scripts/firehose/harvest_teaching_datasets.py | ORANGE | teaching | P2 |
| backend/scripts/firehose/harvest_business_datasets.py | ORANGE | business, accounting | P1 |
| backend/scripts/firehose/harvest_accounting_datasets.py | ORANGE | accounting | P2 |
| backend/scripts/firehose/firehose_orchestrator.py | ORANGE | ALL | P0 |
| backend/scripts/firehose/progress_tracker.py | ORANGE | ALL | P0 |
| backend/app/services/graph_clustering.py | GREEN | ALL | P1 |
| backend/app/services/meta_crystal_synthesizer.py | GREEN | ALL | P1 |
| backend/app/services/constellation_retrieval.py | GREEN | ALL | P1 |


## 15.1 Firehose Orchestrator

The firehose_orchestrator.py is the master controller that runs on ORANGE and sequences all harvest scripts:

```python
"""
Firehose Orchestrator - runs on ORANGE (Hetzner)
Sequences all harvest scripts with progress tracking and error recovery.

Usage:
  nohup python -m backend.scripts.firehose.firehose_orchestrator > /var/log/firehose.log 2>&1 &

Features:
  - Resumable: tracks progress in SQLite, restarts from last checkpoint
  - Rate-limited: respects API quotas (GitHub 5K/hr, SO dump is offline)
  - Priority-ordered: P0 sources first, P2 last
  - Monitored: writes status to /var/log/firehose_status.json every 60s
  - Ships fragments to GREEN via existing crystal sync pipeline
"""
```


---

# 16. CROSS-DOMAIN CONSTELLATION EXAMPLES

The firehose's true power isn't in any single domain — it's in the cross-domain constellations that emerge when the graph is dense across all 8 categories.


## 16.1 Coaching Client: Lawyer Under Stress

**Query:** "I'm a litigation attorney and I can't stop thinking about my cases at night. I'm losing sleep."

Constellation retrieval pulls:
- Clinical crystal (CounselChat): Cognitive restructuring techniques for work-related rumination
- Legal crystal (Pile-of-Law): Litigation timeline patterns and case management expectations
- Crisis crystal (JHU): Sleep disruption as early warning sign for burnout and depression
- PMP crystal: Workload management frameworks, delegation principles for complex projects
- Coaching crystal (PubMed): Research on burnout prevalence among legal professionals


## 16.2 Coaching Client: Machinist Learning PMP

**Query:** "I'm a shop floor supervisor trying to get my PMP. How do I translate my CNC experience into project management language?"

Constellation retrieval pulls:
- Machining crystal (LinuxCNC): CNC workflow structure maps to WBS in PMBOK
- PMP crystal: PMBOK knowledge areas explained with manufacturing analogies
- Teaching crystal: Adult learning theory — bridging experiential knowledge to formal frameworks
- Business crystal: ROI of PMP certification in manufacturing sector


## 16.3 Coaching Client: Teacher Starting a Business

**Query:** "I've been teaching for 15 years and want to start a tutoring business. I don't know anything about accounting or taxes."

Constellation retrieval pulls:
- Teaching crystal: Pedagogy principles that transfer to tutoring business model
- Business crystal: Small business startup checklist, LLC formation
- Accounting crystal (Frappe Books): Double-entry bookkeeping basics for service businesses
- Clinical crystal: Identity transition from employee to entrepreneur — therapeutic implications
- Legal crystal: Independent contractor vs. employee classification, liability considerations


---

# 17. COST MODEL

| Item | One-Time Cost | Monthly Cost | Notes |
|------|--------------|-------------|-------|
| Hetzner CAX41 | — | $28 | Already running |
| DigitalOcean VPS | — | Existing | Already running |
| Cloudflare stack | — | $0 | Free tier covers 474K crystals |
| R2 storage (474K crystals) | — | $0 | Well within 10GB free tier |
| Grok synthesis (acceleration) | $30–42 | — | One-time during bulk ingestion |
| SO dump storage | $0.50 | — | R2 for raw dump |
| All HuggingFace datasets | $0 | — | Free, CC-licensed |
| All PubMed OA articles | $0 | — | Free, CC-licensed, FTP bulk |
| All GitHub repos | $0 | — | Public repos, git clone |
| **TOTAL** | **~$42** | **~$28/month** | **Post-firehose: Grok drops to ~$2/mo** |

As LOCKED crystal coverage increases from 5% to 60%+, the monthly Grok cost drops from baseline to ~$2/month. The system approaches asymptotic $0 variable cost per query.


---

# 18. IMPLEMENTATION NOTES FOR LITTLE NATE BUILD TEAM


## 18.1 Build Order (Critical Path)

1. Day 1: Fix Gap A (fetch_relevant, 30 lines) + Gap B (FederatedSearch BLUE, 40 lines)
2. Day 1: Create backend/scripts/firehose/ directory + progress_tracker.py + firehose_orchestrator.py
3. Day 2: Build harvest_huggingface_therapy.py — test with CounselChat (smallest, fastest feedback loop)
4. Day 2–3: Build harvest_github_deep.py — test with tiangolo/fastapi single repo
5. Day 3–4: Build harvest_stackoverflow_dump.py — download begins (18GB, 2–4 hours on Hetzner 1Gbps)
6. Day 4–5: Build harvest_legal_datasets.py — Pile-of-Law is the single largest source
7. Day 5–7: Build remaining dojo harvest scripts (PMP, machining, teaching, business, accounting)
8. Day 7–10: Build harvest_pubmed_therapy.py — PubMed FTP bulk download + XML parsing
9. Week 2: Build graph_clustering.py + constellation_retrieval.py + meta_crystal_synthesizer.py
10. Week 2+: Deploy firehose_orchestrator.py on ORANGE, monitor via /var/log/firehose_status.json


## 18.2 Domain Registration

The existing domain list in the crystallizer needs to be extended to include the new dojo domains. Add to DOMAIN_RETENTION_FLOORS and all domain routing logic:

```python
NEW_DOMAINS = ["legal", "pmp", "machining", "teaching", "business", "accounting"]
# These supplement existing: coding, clinical, crisis, coaching, general, marketing, conversation
```


## 18.3 Stack Overflow Dump Multi-Domain Routing

The SO dump is a single 18GB file but serves ALL domains. The harvest script must route fragments to the correct domain based on tag intersection:

```python
TAG_DOMAIN_MAP = {
    "python|fastapi|asyncio|websocket": "coding",
    "project-management|agile|scrum": "pmp",
    "cnc|g-code|machining|lathe|milling": "machining",
    "education|pedagogy|teaching": "teaching",
    "business-logic|erp|invoicing|crm": "business",
    "accounting|bookkeeping|gaap|tax": "accounting",
    # Legal tags are sparse on SO — legal domain fed primarily by Pile-of-Law
}
```


## 18.4 Brand Compliance

Per standing instruction: only "Sovereign Sanctuary" and "Little Nate" appear on all documentation and deliverables. Never "Clinical Sovereignty Lab."


---

END OF SPECIFICATION

© 2026 Sovereign Sanctuary. All rights reserved. Patent Pending.
