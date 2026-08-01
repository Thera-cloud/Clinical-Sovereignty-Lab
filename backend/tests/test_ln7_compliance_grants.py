"""Phase E3 — compliance grants offline fences (importlib — avoid numpy FPE).

Covers:
  - ln7_compliance_grants.extract_tables_from_sql(): regex table extraction
    (FROM/JOIN/INTO/UPDATE/DELETE FROM), ignores unnest()/generate_series().
  - ln7_compliance_grants.allowed_tables_for("growth") loads
    frozen-config/compliance_grants.json correctly.
  - ln7_compliance_grants.violations_for_domain("growth", repo_root) is EMPTY
    against the real repo: every SQL table referenced anywhere under
    backend/app/services/growth/ + growth_claims.py is on the grant allowlist.
    This is the live guardrail — a new query against `users`,
    `conversation_history`, `nevedal_metrics`, `sensitive_bridge_*`, or any
    other clinical/PII table added to the growth domain will fail this test
    until either (a) the code is fixed to not touch that table, or (b) an
    engineer deliberately widens frozen-config/compliance_grants.json (and
    updates manifest.sha256.json) — a reviewable, explicit act.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
SERVICES = APP / "services"
REPO_ROOT = BACKEND.parent


def _ensure_pkg(name: str, path: Path) -> None:
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = [str(path)]  # type: ignore[attr-defined]
        sys.modules[name] = pkg


def _load(name: str, path: Path):
    _ensure_pkg("app", APP)
    _ensure_pkg("app.services", SERVICES)
    if name in sys.modules and getattr(sys.modules[name], "__file__", None) == str(path):
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _grants_mod():
    return _load("app.services.ln7_compliance_grants", SERVICES / "ln7_compliance_grants.py")


def test_extract_tables_from_sql_basic():
    g = _grants_mod()
    sql = """
        SELECT * FROM buyer_leads WHERE id = $1
        UNION
        SELECT * FROM Growth_Config
    """
    assert g.extract_tables_from_sql(sql) == {"buyer_leads", "growth_config"}


def test_extract_tables_ignores_set_returning_functions():
    g = _grants_mod()
    sql = "SELECT * FROM unnest($1::text[]) AS x JOIN growth_claims gc ON true"
    tables = g.extract_tables_from_sql(sql)
    assert "unnest" not in tables
    assert "growth_claims" in tables


def test_extract_tables_covers_insert_update_delete():
    g = _grants_mod()
    assert "buyer_leads" in g.extract_tables_from_sql("INSERT INTO buyer_leads (id) VALUES ($1)")
    assert "buyer_leads" in g.extract_tables_from_sql("UPDATE buyer_leads SET status = $1")
    assert "buyer_leads" in g.extract_tables_from_sql("DELETE FROM buyer_leads WHERE id = $1")


def test_growth_domain_grant_loads_and_is_nonempty():
    g = _grants_mod()
    allowed = g.allowed_tables_for("growth")
    assert "growth_claims" in allowed
    assert "buyer_leads" in allowed
    # The whole point of E3: clinical/PII tables must never be grantable.
    # "users" IS granted (see narrow_exceptions in compliance_grants.json —
    # growth_claims.py only clears its own growth-owned JSONB keys there),
    # but true clinical/session tables must never appear.
    for banned in ("conversation_history", "nevedal_metrics", "client_metrics", "session_memories"):
        assert banned not in allowed


def test_growth_domain_paths_resolve_to_real_files():
    g = _grants_mod()
    files = g.files_for_domain("growth", REPO_ROOT)
    assert len(files) > 5
    assert any(f.name == "growth_claims.py" for f in files)


def test_growth_domain_has_zero_compliance_violations():
    """Live guardrail against the real repo tree — see module docstring."""
    g = _grants_mod()
    violations = g.violations_for_domain("growth", REPO_ROOT)
    assert violations == {}, (
        "Growth/marketing domain code references tables outside its compliance "
        f"grant (frozen-config/compliance_grants.json): {violations}"
    )


def test_synthetic_pii_reference_is_caught(tmp_path, monkeypatch):
    """Prove the fence actually fires: point the grant at a temp dir containing
    a file that queries a disallowed clinical table."""
    g = _grants_mod()
    fake_domain_dir = tmp_path / "growth_like"
    fake_domain_dir.mkdir()
    (fake_domain_dir / "leaky.py").write_text(
        'SQL = "SELECT * FROM conversation_history WHERE user_id = $1"\n',
        encoding="utf-8",
    )
    frozen_dir = tmp_path / "frozen-config"
    frozen_dir.mkdir()
    (frozen_dir / "compliance_grants.json").write_text(
        '{"version": 1, "domains": {"growth": {'
        '"paths": ["growth_like/"], "allowed_tables": ["buyer_leads"]}}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("FROZEN_CONFIG_DIR", str(frozen_dir))
    violations = g.violations_for_domain("growth", tmp_path)
    assert "growth_like/leaky.py" in violations
    assert "conversation_history" in violations["growth_like/leaky.py"]
