"""CLI-Cloud discovery: code-first search, data exclusion, truncation warnings."""

import os
import tempfile
from pathlib import Path

import pytest

from app.websocket.cli_chat_handler import _format_tool_result
from app.websocket.cli_tools import (
    _path_discovery_priority,
    _repo_map_sync,
    _search_code_sync,
    _should_skip_path,
)


@pytest.fixture()
def discovery_tree(monkeypatch, tmp_path):
    """Synthetic project: noise in data/ plus real Nevedal Lab sources."""
    (tmp_path / "data" / "Vaults").mkdir(parents=True)
    (tmp_path / "app" / "services").mkdir(parents=True)
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "mobile" / "lib").mkdir(parents=True)
    (tmp_path / "migrations").mkdir()

    # Noise that previously filled the 20-match budget
    for i in range(30):
        (tmp_path / "data" / "Vaults" / f"sms_{i}.json").write_text(
            f'{{"note": "Nevedal SMS log entry {i}"}}\n', encoding="utf-8",
        )

    (tmp_path / "app" / "services" / "nevedal_engine.py").write_text(
        "class NevedalEngine:\n    def compute(self):\n        pass\n",
        encoding="utf-8",
    )
    (tmp_path / "app" / "services" / "nevedal_lab_auditor.py").write_text(
        "TAB_ENDPOINTS = []\nclass NevedalLabAuditor:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "dashboard" / "nevedal_lab_family.html").write_text(
        "<!-- Nevedal Lab Family Dynamics -->\n", encoding="utf-8",
    )
    (tmp_path / "mobile" / "lib" / "nevedal_flutter.dart").write_text(
        "// Nevedal Flutter bridge\nclass NevedalService {}\n", encoding="utf-8",
    )
    (tmp_path / "migrations" / "001_nevedal.sql").write_text(
        "CREATE TABLE nevedal_metrics (id BIGSERIAL);\n", encoding="utf-8",
    )

    monkeypatch.setenv("CLI_PROJECT_ROOT", str(tmp_path))
    # Force local root (not Docker /app)
    import app.websocket.cli_tools as ct

    monkeypatch.setattr(ct, "_PROJECT_ROOT_LOCAL", str(tmp_path))
    monkeypatch.setattr(ct, "_is_docker", lambda: False)
    return tmp_path


def test_skip_dirs_exclude_data_vaults():
    assert _should_skip_path("data/Vaults/foo.json") is True
    assert _should_skip_path("bridge_data/x") is True
    assert _should_skip_path("app/services/nevedal_engine.py") is False
    assert _should_skip_path("dashboard/nevedal_lab_family.html") is False


def test_code_paths_rank_above_noise():
    assert _path_discovery_priority("app/services/nevedal_engine.py") < _path_discovery_priority(
        "docs/notes.txt"
    )
    assert _path_discovery_priority("dashboard/nevedal_lab.html") < _path_discovery_priority(
        "random.csv"
    )


def test_search_code_finds_nevedal_despite_data_noise(discovery_tree):
    result = _search_code_sync("Nevedal", None, None, 20)
    assert result["status"] == "ok"
    files = {m["file"] for m in result["result"]}
    assert any("nevedal_engine.py" in f for f in files)
    assert any("nevedal_lab" in f or "nevedal_flutter" in f or "001_nevedal" in f for f in files)
    # data/ must not appear
    assert not any(f.startswith("data/") for f in files)
    assert result.get("ranked") == "code_first"


def test_search_code_truncation_warning(discovery_tree):
    # Many unique code matches via broad pattern
    (discovery_tree / "app" / "services" / "extra.py").write_text(
        "\n".join(f"x = 'Nevedal marker {i}'" for i in range(50)),
        encoding="utf-8",
    )
    result = _search_code_sync("Nevedal", None, None, 5)
    assert result["truncated"] is True
    assert result.get("warning")
    assert "NOT exhaustive" in result["warning"]


def test_format_tool_result_surfaces_truncation_warning():
    text = _format_tool_result({
        "status": "ok",
        "truncated": True,
        "warning": "TRUNCATED at 5 matches",
        "result": [{"file": "a.py", "line_num": 1, "line_text": "x"}],
    })
    assert text.startswith("[DISCOVERY WARNING]")
    assert "TRUNCATED" in text


def test_repo_map_code_first(discovery_tree):
    result = _repo_map_sync("", 50)
    assert result["status"] == "ok"
    body = result["result"]
    assert "nevedal_engine.py" in body or "nevedal_lab" in body
    assert "data/Vaults" not in body
