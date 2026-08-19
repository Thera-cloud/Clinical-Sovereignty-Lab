"""INV-1 wall — parse migration 404 + ban therapeutic imports. Offline."""

from pathlib import Path

from _studio_load import load_svc

_inv = load_svc("studio_invariants")
THERAPEUTIC_IMPORT_BAN = _inv.THERAPEUTIC_IMPORT_BAN
WALL_TABLES = _inv.WALL_TABLES

ROOT = Path(__file__).resolve().parents[2]
MIG = ROOT / "backend/migrations/404_studio_roles.sql"
STUDIO_GLOBS = [
    "backend/app/services/studio_*.py",
    "backend/app/routers/sovereign_studio_api.py",
    "backend/app/services/broadcast_persona_resolver.py",
]


def test_migration_404_revokes_wall_tables():
    sql = MIG.read_text()
    assert "CREATE ROLE studio_runtime" in sql
    assert "REVOKE ALL ON TABLE" in sql
    for table in WALL_TABLES:
        assert table in sql
    assert "pmb_%" in sql
    assert "sensitive_bridge%" in sql


def test_studio_modules_do_not_import_therapeutic():
    hits = []
    files = []
    for glob in STUDIO_GLOBS:
        files.extend(ROOT.glob(glob))
    for path in files:
        if path.name == "studio_invariants.py":
            continue
        text = path.read_text()
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if not stripped.startswith(("import ", "from ")):
                continue
            for name in THERAPEUTIC_IMPORT_BAN:
                if name in stripped:
                    hits.append(f"{path.name}:{stripped}")
    assert hits == []


def test_no_drop_in_studio_migrations():
    for i in range(400, 408):
        matches = list((ROOT / "backend/migrations").glob(f"{i}_*.sql"))
        assert matches, f"missing migration {i}"
        body = matches[0].read_text().upper()
        assert "DROP TABLE" not in body
        assert "DROP COLUMN" not in body
