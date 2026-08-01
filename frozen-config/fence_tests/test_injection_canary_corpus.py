"""Fence: R4 layer 3 — standing injection-canary corpus.

frozen-config/injection_canary_corpus.json pins a small, versioned set of
known-malicious and known-benign text samples. This test runs every sample
through the live app.services.ln7_injection_firewall scanners on every CI
run, so:

  - a firewall refactor that silently narrows detection coverage (e.g. an
    edit to the regex, or dropping a honeytoken from HONEYTOKENS) fails CI
    immediately instead of only showing up the next time a real attack is
    tried in production, and
  - a false-positive regression (benign task notes start tripping the
    firewall) is also caught, since an overly-broad detector that redacts
    legitimate content is itself an availability regression for the
    flywheel loops that depend on publish_task() notes surviving intact.

New attack shapes discovered in the wild get added to the "malicious" list
here rather than only fixed ad hoc in the scanner — the corpus is the
regression memory, not just the code.

Lives under frozen-config (Queens SA must not write this tree).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent


def _load_corpus() -> Dict[str, Any]:
    return json.loads((ROOT / "injection_canary_corpus.json").read_text(encoding="utf-8"))


def _load_firewall_module():
    """Load ln7_injection_firewall.py by file path, NOT via ``app.services``
    (mirrors backend/scripts/run_ci_tests.sh's Sovereign Standard gate
    loader) — importing the ``app.services`` package pulls in
    nevedal_engine.py -> numpy, which SIGFPEs on some macOS hosts during
    package __init__. The module has no app.* imports at top level (its
    only cross-module import, flywheel_anomaly, is lazy/inside a function),
    so a direct file-path load is safe and avoids the whole package import.
    """
    mod_path = REPO_ROOT / "backend" / "app" / "services" / "ln7_injection_firewall.py"
    spec = importlib.util.spec_from_file_location("ln7_injection_firewall", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_corpus_has_malicious_and_benign_samples():
    corpus = _load_corpus()
    assert len(corpus.get("malicious") or []) >= 3
    assert len(corpus.get("benign") or []) >= 3


def test_every_malicious_sample_trips_scan_honeytokens():
    fw = _load_firewall_module()
    corpus = _load_corpus()
    for sample in corpus["malicious"]:
        hit = fw.scan_honeytokens(sample["text"])
        assert hit is not None, f"malicious sample not caught: {sample['id']}"
        assert hit == sample["expect_token"], (
            f"{sample['id']}: expected token {sample['expect_token']!r}, got {hit!r}"
        )


def test_every_malicious_sample_trips_sanitize_notes():
    fw = _load_firewall_module()
    corpus = _load_corpus()
    for sample in corpus["malicious"]:
        out = fw.sanitize_notes(sample["text"])
        assert out["tripped"] is True, f"sanitize_notes missed: {sample['id']}"
        assert "REDACTED_BY_R4_FIREWALL" in out["notes"]
        # Raw attack text must never survive into the sanitized notes —
        # this is the serialization-boundary guarantee itself.
        assert sample["text"] not in out["notes"]


def test_every_benign_sample_passes_scan_honeytokens():
    fw = _load_firewall_module()
    corpus = _load_corpus()
    for sample in corpus["benign"]:
        hit = fw.scan_honeytokens(sample["text"])
        assert hit is None, f"false positive on benign sample: {sample['id']} (hit={hit!r})"


def test_every_benign_sample_passes_sanitize_notes_unmodified():
    fw = _load_firewall_module()
    corpus = _load_corpus()
    for sample in corpus["benign"]:
        out = fw.sanitize_notes(sample["text"])
        assert out["tripped"] is False, f"false positive on benign sample: {sample['id']}"
        assert out["notes"] == sample["text"]
