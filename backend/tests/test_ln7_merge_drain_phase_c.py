"""Phase C dare_ties merge drain: abort gate authority + orchestration (importlib —
avoid numpy FPE, mirrors test_ln7_hive_burst_phase_a.py's loading pattern).

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
SERVICES = APP / "services"


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


def _md():
    return _load("app.services.ln7_merge_drain", SERVICES / "ln7_merge_drain.py")


class FakeConn:
    """Sequenced fetchrow results for successive heldout_rate() calls."""

    def __init__(self, fetchrow_results=None):
        self._results = list(fetchrow_results or [])
        self.executed = []

    async def fetchrow(self, *_a, **_k):
        if not self._results:
            return None
        return self._results.pop(0)

    async def fetch(self, *_a, **_k):
        return []

    async def execute(self, query, *args):
        self.executed.append((query, args))


class FakePool:
    def __init__(self, conn: FakeConn):
        self._conn = conn

    def acquire(self):
        return self

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_a):
        pass


def _row(n: float, wins: float):
    return {"n": n, "wins": wins}


# ---------------------------------------------------------------------------
# Pure / sync helpers
# ---------------------------------------------------------------------------

def test_check_disk_space_returns_dict_with_free_gb():
    md = _md()
    out = md.check_disk_space()
    assert "ok" in out and "free_gb" in out and "min_gb" in out
    assert out["min_gb"] == md.MIN_FREE_GB


def test_mergekit_yaml_dare_ties_no_target_model_no_relisted_base():
    md = _md()
    yaml_text = md.mergekit_yaml_dare_ties(
        [{"path": "/tmp/a"}, {"path": "/tmp/b"}], density=0.6
    )
    assert "target_model:" not in yaml_text
    assert yaml_text.count("base_model:") == 1
    assert "merge_method: dare_ties" in yaml_text
    assert "/tmp/a" in yaml_text and "/tmp/b" in yaml_text


def test_materialize_peft_to_hf_dry_run_returns_cmd():
    md = _md()
    out = md.materialize_peft_to_hf("/adapters/a", "/tmp/hf/a", dry_run=True)
    assert out["ok"] is True
    assert out["dry_run"] is True
    assert "python3" in out["cmd"]


def test_run_mergekit_dry_run_returns_cmd():
    md = _md()
    out = md.run_mergekit("merge_method: dare_ties\n", "/tmp/merged", dry_run=True)
    assert out["ok"] is True
    assert "mergekit-yaml" in out["cmd"]


def test_convert_to_gguf_dry_run_returns_cmds():
    md = _md()
    out = md.convert_to_gguf("/tmp/merged", "/tmp/out.gguf", dry_run=True)
    assert out["ok"] is True
    assert out["convert_cmd"][0] == "python3"
    assert out["quantize_cmd"][2] == "/tmp/out.gguf"


def test_transfer_gguf_to_orange_dry_run_uses_proxyjump():
    md = _md()
    out = md.transfer_gguf_to_orange("/tmp/out.gguf", "LN7-merge-1", dry_run=True)
    assert out["ok"] is True
    assert "ProxyJump=root@68.183.168.75" in out["scp_cmd"]
    assert "10.13.13.5" in out["remote_path"]


# ---------------------------------------------------------------------------
# abort_gate — the authority: beat incumbent AND every contributor on held-out
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_abort_gate_no_db_rejects():
    md = _md()
    out = await md.abort_gate(
        None, merge_revision_id="LN7-merge-1", contributor_ids=["a", "b"]
    )
    assert out["accept"] is False
    assert out["reason"] == "no_db"


@pytest.mark.asyncio
async def test_abort_gate_rejects_below_incumbent():
    md = _md()
    # merge: 5/10=0.5, incumbent: 8/10=0.8 -> reject below_incumbent
    conn = FakeConn([_row(10, 5), _row(10, 8)])
    pool = FakePool(conn)
    out = await md.abort_gate(
        pool, merge_revision_id="LN7-merge-1", contributor_ids=[], incumbent_id="LN7-fast-baseline"
    )
    assert out["accept"] is False
    assert out["reason"] == "below_incumbent"


@pytest.mark.asyncio
async def test_abort_gate_rejects_below_contributor():
    md = _md()
    # merge: 8/10=0.8, incumbent: 5/10=0.5 (beats), contributor: 9/10=0.9 (loses)
    conn = FakeConn([_row(10, 8), _row(10, 5), _row(10, 9)])
    pool = FakePool(conn)
    out = await md.abort_gate(
        pool,
        merge_revision_id="LN7-merge-1",
        contributor_ids=["LN7-A"],
        incumbent_id="LN7-fast-baseline",
    )
    assert out["accept"] is False
    assert out["reason"] == "below_contributor"
    assert out["contributor"] == "LN7-A"


@pytest.mark.asyncio
async def test_abort_gate_accepts_when_beats_incumbent_and_all_contributors():
    md = _md()
    # merge: 9/10=0.9 beats incumbent 5/10=0.5 and contributor 6/10=0.6
    conn = FakeConn([_row(10, 9), _row(10, 5), _row(10, 6)])
    pool = FakePool(conn)
    out = await md.abort_gate(
        pool,
        merge_revision_id="LN7-merge-1",
        contributor_ids=["LN7-A"],
        incumbent_id="LN7-fast-baseline",
    )
    assert out["accept"] is True
    assert out["mergekit_pin"] == md.PINNED_MERGEKIT


@pytest.mark.asyncio
async def test_abort_gate_no_heldout_data_for_merge_rejects():
    md = _md()
    conn = FakeConn([_row(0, 0)])  # n < 1 -> None
    pool = FakePool(conn)
    out = await md.abort_gate(
        pool, merge_revision_id="LN7-merge-1", contributor_ids=[]
    )
    assert out["accept"] is False
    assert out["reason"] == "merge_no_heldout"


# ---------------------------------------------------------------------------
# prune_micro_experts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prune_micro_experts_marks_each_contributor():
    md = _md()
    conn = FakeConn()
    pool = FakePool(conn)
    out = await md.prune_micro_experts(
        pool, ["LN7-A", "LN7-B"], merge_revision_id="LN7-merge-1"
    )
    assert out["ok"] is True
    assert set(out["pruned"]) == {"LN7-A", "LN7-B"}
    assert len(conn.executed) == 2
    for _query, args in conn.executed:
        assert args[1] == "LN7-merge-1"


@pytest.mark.asyncio
async def test_prune_micro_experts_no_db_returns_not_ok():
    md = _md()
    out = await md.prune_micro_experts(None, ["LN7-A"], merge_revision_id="LN7-merge-1")
    assert out["ok"] is False
    assert out["pruned"] == []


# ---------------------------------------------------------------------------
# run_merge_drain — orchestration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_merge_drain_requires_two_contributors():
    md = _md()
    out = await md.run_merge_drain(None, contributor_ids=["only-one"], dry_run=True)
    assert out["ok"] is False
    assert out["error"] == "need_at_least_2_contributors"


@pytest.mark.asyncio
async def test_run_merge_drain_lease_held_blocks():
    md = _md()
    _load("app.services.ln7_change_lease", SERVICES / "ln7_change_lease.py")
    _load("app.services.flywheel_anomaly", SERVICES / "flywheel_anomaly.py")
    with patch("app.services.ln7_change_lease.acquire_lease", return_value=None):
        out = await md.run_merge_drain(
            None, contributor_ids=["LN7-A", "LN7-B"], dry_run=True
        )
    assert out["ok"] is False
    assert out["error"] == "lease_held"


@pytest.mark.asyncio
async def test_run_merge_drain_dry_run_accept_path_prunes_and_registers():
    md = _md()
    _load("app.services.ln7_change_lease", SERVICES / "ln7_change_lease.py")
    _load("app.services.flywheel_anomaly", SERVICES / "flywheel_anomaly.py")
    _load("app.services.ln7_revision", SERVICES / "ln7_revision.py")
    _load("app.services.ln7_outcome_envelope", SERVICES / "ln7_outcome_envelope.py")

    md._fetch_contributor_rows = AsyncMock(
        return_value={
            "LN7-A": {"adapter_uri": "/adapters/a", "domain_tag": "clinical"},
            "LN7-B": {"adapter_uri": "/adapters/b", "domain_tag": "coaching"},
        }
    )
    md.abort_gate = AsyncMock(
        return_value={"accept": True, "merge_rate": 0.9, "incumbent_rate": 0.5}
    )
    prune_mock = AsyncMock(return_value={"ok": True, "pruned": ["LN7-A", "LN7-B"]})
    md.prune_micro_experts = prune_mock

    with patch("app.services.ln7_change_lease.acquire_lease", return_value="lease1"):
        with patch("app.services.ln7_change_lease.release_lease", return_value=True) as rel:
            with patch(
                "app.services.ln7_revision.register_revision",
                new=AsyncMock(return_value={"ok": True}),
            ) as reg:
                with patch(
                    "app.services.ln7_outcome_envelope.write_envelope",
                    new=AsyncMock(return_value="env-1"),
                ):
                    out = await md.run_merge_drain(
                        object(),
                        contributor_ids=["LN7-A", "LN7-B"],
                        dry_run=True,
                        notes="test merge",
                    )

    assert out["ok"] is True
    assert out["abort_gate"]["accept"] is True
    assert out["gguf"]["ok"] is True
    assert prune_mock.called
    assert rel.called
    # register_revision called at least twice: draft registration + accepted status
    assert reg.call_count >= 2
    # every register_revision call must carry harness_config so provenance
    # (merge_of/mergekit_pin) is never wiped by the ON CONFLICT overwrite
    for _call in reg.call_args_list:
        assert _call.kwargs.get("harness_config") is not None
        assert _call.kwargs.get("harness_config").get("merge_of") == [
            "LN7-A", "LN7-B",
        ]


@pytest.mark.asyncio
async def test_run_merge_drain_rejected_path_does_not_prune():
    md = _md()
    _load("app.services.ln7_change_lease", SERVICES / "ln7_change_lease.py")
    _load("app.services.flywheel_anomaly", SERVICES / "flywheel_anomaly.py")
    _load("app.services.ln7_revision", SERVICES / "ln7_revision.py")
    _load("app.services.ln7_outcome_envelope", SERVICES / "ln7_outcome_envelope.py")

    md._fetch_contributor_rows = AsyncMock(
        return_value={
            "LN7-A": {"adapter_uri": "/adapters/a"},
            "LN7-B": {"adapter_uri": "/adapters/b"},
        }
    )
    md.abort_gate = AsyncMock(
        return_value={"accept": False, "reason": "below_incumbent"}
    )
    prune_mock = AsyncMock(return_value={"ok": True, "pruned": []})
    md.prune_micro_experts = prune_mock

    with patch("app.services.ln7_change_lease.acquire_lease", return_value="lease1"):
        with patch("app.services.ln7_change_lease.release_lease", return_value=True):
            with patch(
                "app.services.ln7_revision.register_revision",
                new=AsyncMock(return_value={"ok": True}),
            ):
                with patch(
                    "app.services.ln7_outcome_envelope.write_envelope",
                    new=AsyncMock(return_value="env-1"),
                ):
                    out = await md.run_merge_drain(
                        object(),
                        contributor_ids=["LN7-A", "LN7-B"],
                        dry_run=True,
                    )

    assert out["ok"] is True  # orchestration succeeded; merge correctly rejected
    assert out["accepted"] is False
    assert not prune_mock.called


@pytest.mark.asyncio
async def test_run_merge_drain_missing_adapter_uri_errors():
    md = _md()
    _load("app.services.ln7_change_lease", SERVICES / "ln7_change_lease.py")
    _load("app.services.flywheel_anomaly", SERVICES / "flywheel_anomaly.py")

    md._fetch_contributor_rows = AsyncMock(return_value={})

    with patch("app.services.ln7_change_lease.acquire_lease", return_value="lease1"):
        with patch("app.services.ln7_change_lease.release_lease", return_value=True) as rel:
            out = await md.run_merge_drain(
                object(), contributor_ids=["LN7-A", "LN7-B"], dry_run=True
            )

    assert out["error"].startswith("missing_adapter_uri:")
    assert rel.called  # lease released even on early-return error path
