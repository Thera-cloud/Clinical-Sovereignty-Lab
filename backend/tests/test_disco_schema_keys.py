"""Schema-key reconciliation — live tables only, no spec fiction."""

from pathlib import Path

from app.services.disco.schema_keys import FORBIDDEN_TABLES, IDENTITY_KEY, SCHEMA_KEYS, all_live_tables


DISCO_DIR = Path(__file__).resolve().parents[1] / "app" / "services" / "disco"


def test_identity_is_users_username():
    assert IDENTITY_KEY == ("users", "username")
    assert SCHEMA_KEYS["credentials"]["identity"] == ("users", "username")
    assert SCHEMA_KEYS["credentials"]["credential_rows"] == ("coach_credentials", "coach_id")


def test_tokens_are_workspace_and_calendar_not_google_credentials():
    assert SCHEMA_KEYS["credentials"]["token_workspace"][0] == "google_workspace_connection"
    assert SCHEMA_KEYS["credentials"]["token_calendar"][0] == "google_calendar_connection"
    assert "google_credentials" not in all_live_tables()
    assert "coaches" not in all_live_tables()


def test_four_contracts_map_to_live_tables():
    assert SCHEMA_KEYS["engagements"]["table"][0] == "campaign_engagements"
    assert SCHEMA_KEYS["content_topics"]["v15"][0] == "content_topics"
    assert SCHEMA_KEYS["content_topics"]["coach_flagged"][0] == "disco_content_topics"
    assert SCHEMA_KEYS["authoring"]["table"][0] == "marketing_content"


def test_disco_package_sql_avoids_forbidden_tables():
    hits = []
    for path in DISCO_DIR.glob("*.py"):
        text = path.read_text()
        for bad in FORBIDDEN_TABLES:
            if f"FROM {bad}" in text or f"INTO {bad}" in text or f"'{bad}'" in text and "FORBIDDEN" not in text:
                if bad in text and path.name != "schema_keys.py":
                    if f"FROM {bad}" in text or f"JOIN {bad}" in text:
                        hits.append(f"{path.name}:{bad}")
    assert hits == []
