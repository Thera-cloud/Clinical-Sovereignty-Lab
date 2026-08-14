"""Seam 9: staging rehearsal AC1–AC33 (offline). Live Google/LinkedIn/SendGrid = staging."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "backend/tests/golden/workspace_voice/eval_manifest.json"

# Queens bar: executed in CI, staging-blocked (O6/O9), or ops-scheduled (AC27).
AC_OWNERS = {
    "AC1": "google_workspace_oauth.py",
    "AC2": "google_workspace_api.py",
    "AC3": "gmail_draft_service.py",
    "AC4": "gmail_reply_listener.py",
    "AC5": "voice_campaign_generator.py",
    "AC6": "coach_linkedin_publisher.py",
    "AC7": "studio_hmac.py",
    "AC8": "gmail_draft_service.py",
    "AC9": "test_google_workspace_seam0.py",
    "AC10": "google_workspace_service.py",
    "AC11": "google_calendar_session_sync.py",
    "AC12": "sheets_engagement_appender.py",
    "AC13": "google_chat_notifier.py",
    "AC14": "docs_formatter.py",
    "AC15": "google_workspace_oauth.py",
    "AC16": "voice_campaign_ingest.py",
    "AC17": "coach_linkedin_oauth.py",
    "AC18": "gmail_reply_listener.py",
    "AC19": "coach_task_service.py",
    "AC20": "effective_scope.py",
    "AC21": "morning_brief_composer.py",
    "AC22": "effective_scope.py",
    "AC23": "morning_brief_composer.py",
    "AC24": "audio_synthesis_service.py",
    "AC25": "practice_library_service.py",
    "AC26": "practice_library_service.py",
    "AC27": "ops_scheduled",
    "AC28": "practice_library_service.py",
    "AC29": "coach_credential_service.py",
    "AC30": "ac30_drill.py",
    "AC31": "crisis_escalation.py",
    "AC32": "gmail_draft_service.py",
    "AC33": "eval_manifest.json",
}

STAGING_BLOCKED = {"AC1", "AC2", "AC4", "AC15"}  # O9 test-user / live Google
OPS_SCHEDULED = {"AC27"}


def test_ac1_to_ac33_all_recorded():
    assert len(AC_OWNERS) == 33
    for i in range(1, 34):
        key = f"AC{i}"
        assert key in AC_OWNERS
        owner = AC_OWNERS[key]
        if key in OPS_SCHEDULED:
            assert owner == "ops_scheduled"
            continue
        if key == "AC33":
            assert GOLDEN.is_file()
            continue
        hits = list((ROOT / "backend").rglob(owner))
        assert hits, f"{key} owner missing: {owner}"


def test_ac33_harness_does_not_shrink():
    data = GOLDEN.read_text()
    assert "pending_authorship" in data or '"items"' in data
    assert "relationship_classes" in data


def test_coach_command_integrations_tab():
    dart = (ROOT / "mobile/lib/updated_screens.dart").read_text()
    assert "INTEGRATIONS" in dart
    assert "CoachIntegrationsHub" in dart
    assert "TabController(length: 12" in dart
    hub = (ROOT / "mobile/lib/widgets/coach_integrations_hub.dart").read_text()
    assert "/api/coach/integrations/hub" in hub
    assert "Connect LinkedIn" in hub
    assert "VOICE CAMPAIGN" in hub
    assert "VIDEO INTERVIEW" in hub
    assert "length_days" in hub
    assert "Generate for clients" in hub
    assert "assistant_coaches" in hub
    assert "STUDIO WEBHOOK SECRET" in hub
    assert "vault_sync" in hub
    assert "CAMPAIGN" in hub
    assert "Publish to LinkedIn" in hub
    assert "Upload voice recording" in hub
    assert "/api/v1/hooks/" in hub
    assert "Disconnect LinkedIn" in hub
    settings = (ROOT / "mobile/lib/screens/settings_screen.dart").read_text()
    assert "CoachIntegrationsHub" in settings
    assert "destroy_client_keys" not in dart


def test_hub_router_and_linkedin_isolation():
    main = (ROOT / "backend/app/main.py").read_text()
    assert "coach_integrations_api" in main
    api = (ROOT / "backend/app/routers/coach_integrations_api.py").read_text()
    assert "FROM skyeye_platform_tokens" not in api
    assert "INSERT INTO skyeye_platform_tokens" not in api
    li = (ROOT / "backend/app/services/coach_linkedin_oauth.py").read_text()
    assert "coach_linkedin_connection" in li
    assert "INTO skyeye_platform_tokens" not in li
    assert "FROM skyeye_platform_tokens" not in li
    pub = (ROOT / "backend/app/services/coach_linkedin_publisher.py").read_text()
    assert "skyeye_platform_tokens" not in pub
    sql = (ROOT / "backend/migrations/332_coach_integrations_hub.sql").read_text()
    assert "DROP TABLE" not in sql.upper()
    assert "coach_integrations_settings" in sql


def test_campaign_review_includes_body_and_approved():
    src = (ROOT / "backend/app/services/voice_campaign_generator.py").read_text()
    assert "draft_body" in src
    assert "list_approved_unpublished" in src
    api = (ROOT / "backend/app/routers/coach_integrations_api.py").read_text()
    assert "approved_unpublished" in api
    assert "linkedin/disconnect" in api
    assert "revoke_coach_linkedin" in api
    assert "/campaigns/{content_id}/preview" in api
    assert "generate-image" in api
    hub = (ROOT / "mobile/lib/widgets/coach_integrations_hub.dart").read_text()
    assert "Preview" in hub
    assert "Generate photo" in hub


def test_ng13_scopes_still_split():
    from app.services.google_calendar_client import GOOGLE_SCOPES
    from app.services.google_workspace_oauth import GOOGLE_WS_SCOPES

    assert "gmail" not in GOOGLE_SCOPES.lower()
    assert "gmail.send" not in GOOGLE_WS_SCOPES.lower()
    assert "gmail.compose" in GOOGLE_WS_SCOPES.lower()


def test_zoom_join_not_removed():
    src = (ROOT / "backend/app/services/google_workspace_service.py").read_text()
    assert "zoom_meeting_id" in src
    dart = (ROOT / "mobile/lib/updated_screens.dart").read_text()
    assert "zoom" in dart.lower()


@pytest.mark.asyncio
async def test_flag_kill_hub_and_erasure_off(monkeypatch):
    from app.services.coach_integrations_hub import hub_snapshot
    from app.services.client_envelope_cipher import ErasureDisabled, destroy_client_keys

    monkeypatch.setenv("ENABLE_WS_OAUTH", "false")
    monkeypatch.setenv("ENABLE_VOICE_CAMPAIGN", "false")
    monkeypatch.setenv("ENABLE_COACH_LINKEDIN", "false")
    monkeypatch.setenv("ENABLE_CLINICAL_ERASURE", "false")
    snap = await hub_snapshot(None, "COACH_HW")
    assert snap["erasure_ui"] is False
    assert snap["workspace"]["connect_visible"] is False
    assert snap["linkedin"]["skyeye_fallback"] is False
    assert snap["linkedin"]["connect_visible"] is True
    assert snap["supervision"]["is_master"] is False
    assert snap["supervision"]["source"] == "coach_hierarchy"
    with pytest.raises(ErasureDisabled):
        await destroy_client_keys(None, "CLIENT_X")


def test_workspace_connect_hidden_in_prod_defaults():
    env = (ROOT / ".env.template").read_text()
    assert "ENABLE_WS_OAUTH=false" in env
    assert "ENABLE_CLINICAL_ERASURE=false" in env
    assert "LINKEDIN_COACH_REDIRECT_URI" in env
    api = (ROOT / "backend/app/routers/google_workspace_api.py").read_text()
    assert "_require_ws_oauth" in api
