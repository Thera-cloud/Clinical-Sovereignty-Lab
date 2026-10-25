"""Bridge chat must read vault uploads from the backend data volume."""
import importlib.util
import os
from pathlib import Path


_PATH = os.path.join(
    os.path.dirname(__file__), "..", "app", "services", "vault", "blob_manager.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("vault_blob_paths_test", _PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_absolute_backend_path_also_maps_to_bridge_cross_mount(tmp_path, monkeypatch):
    mod = _load()
    backend = tmp_path / "backend"
    (backend / "archives" / "quarantine").mkdir(parents=True)
    blob = backend / "archives" / "quarantine" / "photo-uuid"
    blob.write_bytes(b"jpeg-bytes")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "bridge"))
    monkeypatch.setenv("BACKEND_DATA_DIR", str(backend))
    stored = "/app/data/archives/quarantine/photo-uuid"
    paths = [str(p) for p in mod.local_blob_paths(stored)]
    assert str(backend / "archives" / "quarantine" / "photo-uuid") in paths
    assert mod.read_local_blob_bytes(stored) == b"jpeg-bytes"


def test_relative_quarantine_key_checks_backend_archives(tmp_path, monkeypatch):
    mod = _load()
    backend = tmp_path / "backend"
    dest = backend / "archives" / "quarantine"
    dest.mkdir(parents=True)
    (dest / "old-shot").write_bytes(b"png")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "bridge"))
    monkeypatch.setenv("BACKEND_DATA_DIR", str(backend))
    assert mod.read_local_blob_bytes("quarantine/old-shot") == b"png"
