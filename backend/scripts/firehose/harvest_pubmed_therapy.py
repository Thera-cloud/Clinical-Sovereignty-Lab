"""
PubMed Therapy Research Harvester — Phase 6a
Fetches therapy outcome research, meta-analyses, and evidence-based
practice guidelines from PubMed/NCBI for clinical + research domains.

Target: 3,000–5,000 crystals across clinical, research, crisis domains.
Node: ORANGE (Hetzner) → ships to GREEN.

Uses NCBI E-utilities API (free, rate limited to 3 requests/sec without API key).

Usage:
  python -m backend.scripts.firehose.harvest_pubmed_therapy
"""

import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional

FIREHOSE_DIR = Path(__file__).parent
sys.path.insert(0, str(FIREHOSE_DIR))
from progress_tracker import ProgressTracker

GREEN_PUSH_URL = os.getenv("GREEN_PUSH_URL", "http://localhost:8000/api/admin/crystal-network/push")
GREEN_AUTH_TOKEN = os.getenv("GREEN_AUTH_TOKEN", "")
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")

MAX_FRAGMENT_LEN = 2000
STAGE1_THRESHOLD = 6
PUSH_BATCH_SIZE = 50
NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

PUBMED_QUERIES = [
    ("CBT effectiveness meta-analysis", "clinical"),
    ("DBT borderline personality disorder outcomes", "clinical"),
    ("EMDR PTSD treatment efficacy", "clinical"),
    ("mindfulness-based cognitive therapy depression", "clinical"),
    ("motivational interviewing substance abuse", "clinical"),
    ("acceptance commitment therapy ACT anxiety", "clinical"),
    ("psychodynamic therapy long-term outcomes", "clinical"),
    ("family therapy systemic approaches effectiveness", "clinical"),
    ("group therapy therapeutic factors Yalom", "clinical"),
    ("telehealth psychotherapy outcomes satisfaction", "clinical"),
    ("therapeutic alliance outcome prediction", "research"),
    ("therapist burnout compassion fatigue", "clinical"),
    ("suicide risk assessment clinical guidelines", "crisis"),
    ("crisis intervention mental health emergency", "crisis"),
    ("trauma-informed care implementation evidence", "clinical"),
    ("cultural competence therapy outcomes", "clinical"),
    ("child adolescent therapy evidence-based", "clinical"),
    ("couples therapy Gottman method research", "clinical"),
    ("attachment theory psychotherapy application", "research"),
    ("neuroscience psychotherapy integration", "research"),
    ("measurement-based care mental health", "research"),
    ("common factors psychotherapy effectiveness", "research"),
    ("therapist training supervision outcomes", "coaching"),
    ("patient-reported outcome measures mental health", "research"),
    ("digital mental health interventions efficacy", "research"),
]


def search_pubmed(query: str, max_results: int = 50) -> List[str]:
    """Search PubMed and return list of PMIDs."""
    import requests
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "sort": "relevance",
        "retmode": "json",
    }
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY

    try:
        resp = requests.get(f"{NCBI_BASE}/esearch.fcgi", params=params, timeout=30)
        if resp.status_code == 200:
            return resp.json().get("esearchresult", {}).get("idlist", [])
    except Exception:
        pass
    return []


def fetch_abstracts(pmids: List[str]) -> List[Dict]:
    """Fetch article details from PubMed."""
    import requests
    if not pmids:
        return []

    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
        "rettype": "abstract",
    }
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY

    try:
        resp = requests.get(f"{NCBI_BASE}/efetch.fcgi", params=params, timeout=60)
        if resp.status_code != 200:
            return []

        root = ET.fromstring(resp.text)
        articles = []

        for article in root.findall(".//PubmedArticle"):
            pmid_el = article.find(".//PMID")
            pmid = pmid_el.text if pmid_el is not None else ""

            title_el = article.find(".//ArticleTitle")
            title = title_el.text if title_el is not None else ""

            abstract_parts = []
            for abs_text in article.findall(".//AbstractText"):
                label = abs_text.get("Label", "")
                text = abs_text.text or ""
                if label:
                    abstract_parts.append(f"{label}: {text}")
                else:
                    abstract_parts.append(text)
            abstract = "\n".join(abstract_parts)

            journal_el = article.find(".//Journal/Title")
            journal = journal_el.text if journal_el is not None else ""

            year_el = article.find(".//PubDate/Year")
            year = year_el.text if year_el is not None else ""

            keywords = []
            for kw in article.findall(".//Keyword"):
                if kw.text:
                    keywords.append(kw.text)

            if abstract and len(abstract) > 80:
                articles.append({
                    "pmid": pmid,
                    "title": title,
                    "abstract": abstract,
                    "journal": journal,
                    "year": year,
                    "keywords": keywords[:10],
                })

        return articles
    except Exception:
        return []


def stage1_filter(text: str, domain: str) -> Optional[int]:
    from common import stage1_ollama_score
    prompt = (
        f"Score this psychotherapy research abstract 1-10 for value as "
        f"crystallized clinical knowledge in {domain}.\n"
        f"Consider: clinical applicability, evidence quality (meta-analysis > "
        f"case study), specificity of findings, relevance to practicing therapists.\n"
        f"Respond with ONLY a number 1-10.\n\n{text[:1000]}"
    )
    return stage1_ollama_score(text, prompt)


def push_to_green(fragments: List[Dict]):
    from common import push_to_green_safe
    push_to_green_safe(
        fragments, domain_default="clinical", fallback_name="pubmed",
        green_push_url=GREEN_PUSH_URL, green_auth_token=GREEN_AUTH_TOKEN or "",
        face_path_prefix="pubmed",
    )


def harvest_pubmed():
    tracker = ProgressTracker()
    tracker.set_status("current_phase", "pubmed")

    total_passed = 0
    push_buffer: List[Dict] = []

    for query, domain in PUBMED_QUERIES:
        qkey = f"pubmed:{query.replace(' ', '_')[:60]}"
        if tracker.is_done("pubmed", qkey):
            continue

        tracker.set_status("current_source", f"pubmed:{query[:40]}")
        print(f"\n[PUBMED] Searching: {query}")

        pmids = search_pubmed(query, max_results=50)
        if not pmids:
            tracker.mark_done("pubmed", qkey, domain=domain, passed=False)
            time.sleep(0.5)
            continue

        articles = fetch_abstracts(pmids)
        print(f"  [{query[:30]}] Fetched {len(articles)} abstracts")

        for art in articles:
            aid = f"pubmed:{art['pmid']}"
            if tracker.is_done("pubmed", aid):
                continue

            kw_str = ", ".join(art["keywords"][:5])
            text = (
                f"[PubMed Research: {art['title']}]\n"
                f"Journal: {art['journal']} ({art['year']})\n"
                f"Keywords: {kw_str}\n\n"
                f"{art['abstract']}"
            )[:MAX_FRAGMENT_LEN]

            score = stage1_filter(text, domain)
            passed = score is not None and score >= STAGE1_THRESHOLD
            tracker.mark_done("pubmed", aid, domain=domain, passed=passed)

            if passed:
                total_passed += 1
                push_buffer.append({
                    "text": text,
                    "source": f"pubmed:{art['pmid']}",
                    "domain": domain,
                    "scope": "global",
                    "source_type": "pubmed",
                })
                if len(push_buffer) >= PUSH_BATCH_SIZE:
                    push_to_green(push_buffer)
                    push_buffer.clear()

        tracker.mark_done("pubmed", qkey, domain=domain)
        time.sleep(0.5)

    if push_buffer:
        push_to_green(push_buffer)

    tracker.set_status("current_source", "complete")
    tracker.write_status_json()
    print(f"\n[PUBMED] Complete — {total_passed} fragments passed Stage 1")
    tracker.close()


if __name__ == "__main__":
    harvest_pubmed()
