from pathlib import Path


def test_feature_flags_exist():
    settings_file = Path(__file__).resolve().parents[1] / "app" / "config" / "_settings.py"
    content = settings_file.read_text()
    assert "ENABLE_QUANTUM_CRYSTAL_ORCHESTRATOR" in content
    assert "ENABLE_VOICE_TRANSCRIPT_CRYSTALLIZATION" in content
    assert "ENABLE_TIME_CRYSTAL_FORGE" in content


def test_main_has_service_check_entry():
    main_path = Path(__file__).resolve().parents[1] / "app" / "main.py"
    content = main_path.read_text()
    assert "quantum_crystal_orchestrator" in content


def test_migration_has_anti_decay_trigger():
    migration_path = Path(__file__).resolve().parents[1] / "migrations" / "154_quantum_crystal_orchestrator.sql"
    sql = migration_path.read_text()
    assert "prevent_crystal_confidence_decay" in sql
    assert "CREATE TRIGGER no_confidence_decay" in sql
