"""R5 — droplet lockfile mirror + R2-mirrored base weights with checksums.

Covers (offline, importlib pattern — avoid numpy FPE per project convention):
  - ln7_droplet_lockfile.verify_droplet_lockfile(): real repo lockfile is fully
    hash-pinned + mirror-declared; synthetic unpinned/undeclared cases fail closed.
  - ln7_r2_weight_mirror.mirror_base_model_dir() / verify_base_model_checksums():
    pin-write, graceful skip when no local checkout, graceful skip when a checkout
    exists but has never been pinned, and fail-closed drift detection once pinned.
  - ln7_fallback_drill.run_fallback_drill() step 5 ("supply_chain_pin") surfaces
    both checks without requiring a live GPU node.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

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


def _frozen_config_mod():
    return _load("app.services.ln7_frozen_config", SERVICES / "ln7_frozen_config.py")


def _droplet_mod():
    _frozen_config_mod()
    return _load("app.services.ln7_droplet_lockfile", SERVICES / "ln7_droplet_lockfile.py")


def _r2_mirror_mod():
    _frozen_config_mod()
    return _load("app.services.ln7_r2_weight_mirror", SERVICES / "ln7_r2_weight_mirror.py")


# ---------------------------------------------------------------------------
# ln7_droplet_lockfile — real repo artifact
# ---------------------------------------------------------------------------

def test_real_droplet_lockfile_is_fully_pinned_and_mirror_declared():
    d = _droplet_mod()
    result = d.verify_droplet_lockfile()
    assert result["ok"] is True, result
    assert result["package_count"] >= 1
    assert result["unpinned"] == []
    assert result["mirror_declared"] is True
    assert result["mirror_url"]


def test_droplet_lockfile_missing_fails_closed(tmp_path, monkeypatch):
    d = _droplet_mod()
    monkeypatch.setenv("FROZEN_CONFIG_DIR", str(tmp_path))
    result = d.verify_droplet_lockfile()
    assert result["ok"] is False
    assert result["error"] == "lockfile_missing"


def test_droplet_lockfile_unpinned_requirement_fails_closed(tmp_path, monkeypatch):
    d = _droplet_mod()
    monkeypatch.setenv("FROZEN_CONFIG_DIR", str(tmp_path))
    (tmp_path / d.LOCKFILE_NAME).write_text(
        "# internal-mirror-index-url: https://pip.example.internal/simple/\n"
        "\n"
        "requests==2.32.3\n"  # no --hash continuation → unpinned
        "\n",
        encoding="utf-8",
    )
    result = d.verify_droplet_lockfile()
    assert result["ok"] is False
    assert "requests==2.32.3" in result["unpinned"]


def test_droplet_lockfile_missing_mirror_declaration_fails_closed(tmp_path, monkeypatch):
    d = _droplet_mod()
    monkeypatch.setenv("FROZEN_CONFIG_DIR", str(tmp_path))
    (tmp_path / d.LOCKFILE_NAME).write_text(
        "requests==2.32.3 \\\n"
        "    --hash=sha256:" + ("a" * 64) + "\n",
        encoding="utf-8",
    )
    result = d.verify_droplet_lockfile()
    assert result["ok"] is False
    assert result["mirror_declared"] is False


def test_droplet_lockfile_fully_pinned_and_declared_passes(tmp_path, monkeypatch):
    d = _droplet_mod()
    monkeypatch.setenv("FROZEN_CONFIG_DIR", str(tmp_path))
    (tmp_path / d.LOCKFILE_NAME).write_text(
        "# internal-mirror-index-url: https://pip.example.internal/simple/\n"
        "requests==2.32.3 \\\n"
        "    --hash=sha256:" + ("a" * 64) + "\n"
        "\n"
        "idna==3.8 \\\n"
        "    --hash=sha256:" + ("b" * 64) + "\n",
        encoding="utf-8",
    )
    result = d.verify_droplet_lockfile()
    assert result["ok"] is True
    assert result["package_count"] == 2
    assert result["unpinned"] == []


# ---------------------------------------------------------------------------
# ln7_r2_weight_mirror — base model checksum pin lifecycle
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_verify_base_model_checksums_skips_when_no_local_checkout(tmp_path, monkeypatch):
    r2 = _r2_mirror_mod()
    monkeypatch.setenv("FROZEN_CONFIG_DIR", str(tmp_path))
    missing_dir = tmp_path / "no_such_base_model_dir"
    result = _run(r2.verify_base_model_checksums(str(missing_dir)))
    assert result == {
        "ok": True,
        "skipped": True,
        "reason": "no_local_checkout",
        "dir": str(missing_dir),
    }


def test_verify_base_model_checksums_skips_when_not_yet_pinned(tmp_path, monkeypatch):
    r2 = _r2_mirror_mod()
    frozen_dir = tmp_path / "frozen-config"
    frozen_dir.mkdir()
    monkeypatch.setenv("FROZEN_CONFIG_DIR", str(frozen_dir))

    local_dir = tmp_path / "base_model"
    local_dir.mkdir()
    (local_dir / "config.json").write_text("{}", encoding="utf-8")

    result = _run(r2.verify_base_model_checksums(str(local_dir)))
    assert result["ok"] is True
    assert result["skipped"] is True
    assert result["reason"] == "not_yet_pinned"


def test_mirror_base_model_dir_writes_pin_and_verify_then_passes(tmp_path, monkeypatch):
    r2 = _r2_mirror_mod()
    frozen_dir = tmp_path / "frozen-config"
    frozen_dir.mkdir()
    monkeypatch.setenv("FROZEN_CONFIG_DIR", str(frozen_dir))

    local_dir = tmp_path / "base_model"
    local_dir.mkdir()
    (local_dir / "config.json").write_text('{"hidden_size": 4096}', encoding="utf-8")
    (local_dir / "tokenizer.json").write_text('{"vocab": []}', encoding="utf-8")

    mirror_result = _run(r2.mirror_base_model_dir(str(local_dir)))
    assert mirror_result["ok"] is True
    assert mirror_result["pin_written"] is True
    assert mirror_result["file_count"] == 2
    manifest_path = frozen_dir / r2.BASE_MODEL_CHECKSUM_FILE
    assert manifest_path.is_file()

    verify_result = _run(r2.verify_base_model_checksums(str(local_dir)))
    assert verify_result["ok"] is True
    assert verify_result.get("skipped") is not True
    assert verify_result["checked_files"] == 2
    assert verify_result["mismatched"] == []
    assert verify_result["missing"] == []
    assert verify_result["extra_unpinned"] == []


def test_verify_base_model_checksums_fails_closed_on_drift(tmp_path, monkeypatch):
    r2 = _r2_mirror_mod()
    frozen_dir = tmp_path / "frozen-config"
    frozen_dir.mkdir()
    monkeypatch.setenv("FROZEN_CONFIG_DIR", str(frozen_dir))

    local_dir = tmp_path / "base_model"
    local_dir.mkdir()
    (local_dir / "config.json").write_text('{"hidden_size": 4096}', encoding="utf-8")

    _run(r2.mirror_base_model_dir(str(local_dir)))

    # Tamper with the file after the pin was established — must be detected.
    (local_dir / "config.json").write_text('{"hidden_size": 9999}', encoding="utf-8")

    result = _run(r2.verify_base_model_checksums(str(local_dir)))
    assert result["ok"] is False
    assert "config.json" in result["mismatched"]


def test_verify_base_model_checksums_fails_closed_on_missing_pinned_file(tmp_path, monkeypatch):
    r2 = _r2_mirror_mod()
    frozen_dir = tmp_path / "frozen-config"
    frozen_dir.mkdir()
    monkeypatch.setenv("FROZEN_CONFIG_DIR", str(frozen_dir))

    local_dir = tmp_path / "base_model"
    local_dir.mkdir()
    (local_dir / "config.json").write_text("{}", encoding="utf-8")
    (local_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
    _run(r2.mirror_base_model_dir(str(local_dir)))

    (local_dir / "tokenizer.json").unlink()

    result = _run(r2.verify_base_model_checksums(str(local_dir)))
    assert result["ok"] is False
    assert "tokenizer.json" in result["missing"]


def test_mirror_adapter_dir_missing_dir_fails_closed():
    r2 = _r2_mirror_mod()
    result = _run(r2.mirror_adapter_dir("/no/such/adapter/dir/at/all"))
    assert result == {"ok": False, "error": "missing_dir"}


def test_mirror_adapter_dir_checksums_and_skips_r2_when_unavailable(tmp_path):
    r2 = _r2_mirror_mod()
    adapter_dir = tmp_path / "adapter_rev_1"
    adapter_dir.mkdir()
    (adapter_dir / "adapter_model.bin").write_bytes(b"fake-lora-weights")

    result = _run(r2.mirror_adapter_dir(str(adapter_dir), revision_id="rev1"))
    assert result["ok"] is True
    assert "adapter_model.bin" in result["checksums"]


# ---------------------------------------------------------------------------
# ln7_fallback_drill — supply_chain_pin step surfaces both checks
# ---------------------------------------------------------------------------

def test_fallback_drill_supply_chain_pin_step_present_in_source():
    """Static check that step 5 wires both verifiers — the full drill also
    exercises hive burst / serve endpoint / fingerprint, which need heavier
    fixtures than this offline module warrants."""
    src = (SERVICES / "ln7_fallback_drill.py").read_text(encoding="utf-8")
    assert "verify_droplet_lockfile" in src
    assert "verify_base_model_checksums" in src
    assert '"id": "supply_chain_pin"' in src
