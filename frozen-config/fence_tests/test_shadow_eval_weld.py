"""Fence: R3 shadow_eval_params.json must stay well-formed and every variant
target must fall inside the code-level safety allowlist
(app.services.ln7_shadow_evaluator.ALLOWED_SHADOW_TARGETS).

The allowlist exists so a shadow variant can only propose changes to a
pure numeric threshold bank already read by a live evaluator — never the
held-out floor, adversarial criteria, or anything that could change what
data trains/blocks (that boundary belongs to Phase H, not R3). A config
edit that adds a disallowed target would silently be ignored at runtime
(app.services.ln7_shadow_evaluator.shadow_drift_bands skips it) rather
than raise loudly, so this fence exists to catch that drift at commit
time instead of silently-never-firing in production.

Lives under frozen-config (Queens SA must not write this tree).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent


def _load() -> dict:
    return json.loads((ROOT / "shadow_eval_params.json").read_text(encoding="utf-8"))


def _load_allowed_shadow_targets() -> frozenset:
    """Load ln7_shadow_evaluator.py by file path, NOT via ``app.services``
    (mirrors backend/scripts/run_ci_tests.sh's Sovereign Standard gate
    loader) — importing the ``app.services`` package pulls in
    nevedal_engine.py -> numpy, which SIGFPEs on some macOS hosts during
    package __init__. The module has no app.* imports at top level, so a
    direct file-path load is safe and avoids the whole package import."""
    mod_path = REPO_ROOT / "backend" / "app" / "services" / "ln7_shadow_evaluator.py"
    spec = importlib.util.spec_from_file_location("ln7_shadow_evaluator", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.ALLOWED_SHADOW_TARGETS


def test_shadow_eval_params_has_required_keys():
    data = _load()
    assert "divergence_threshold" in data
    assert "min_samples" in data
    assert isinstance(data.get("variants"), list)


def test_shadow_eval_divergence_threshold_in_range():
    data = _load()
    threshold = float(data["divergence_threshold"])
    assert 0.0 < threshold <= 1.0


def test_shadow_eval_min_samples_positive():
    data = _load()
    assert int(data["min_samples"]) >= 1


def test_shadow_eval_every_variant_has_required_fields():
    data = _load()
    for variant in data.get("variants") or []:
        assert "id" in variant
        assert "target" in variant
        assert isinstance(variant.get("overlay"), dict)


def test_shadow_eval_variant_targets_match_code_allowlist():
    """R3 absolute: no loop edits its own evaluator. A variant target
    outside the code allowlist would be silently skipped (never applied,
    never diverges, never fires) — catch that drift here instead."""
    allowed = _load_allowed_shadow_targets()

    data = _load()
    targets = {v.get("target") for v in (data.get("variants") or [])}
    disallowed = targets - allowed
    assert not disallowed, (
        f"shadow_eval_params.json targets not in code allowlist: {sorted(disallowed)} "
        f"(allowed: {sorted(allowed)})"
    )


def test_shadow_eval_goodhart_overlay_only_touches_drift_bands():
    """The only sanctioned variant shape today: overlay a candidate
    drift_bands bank onto goodhart_probes.json. Guards against a future
    edit smuggling in unrelated keys (e.g. metrics, probe_scenarios) via
    the overlay path, which would bypass review of what the shadow PR
    could propose."""
    data = _load()
    for variant in data.get("variants") or []:
        if variant.get("target") != "goodhart_probes":
            continue
        overlay_keys = set((variant.get("overlay") or {}).keys())
        assert overlay_keys <= {"drift_bands"}, (
            f"goodhart_probes shadow overlay must only touch drift_bands, got: {sorted(overlay_keys)}"
        )
