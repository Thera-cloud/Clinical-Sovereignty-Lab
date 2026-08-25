"""Dual-COO risk tiers, CEO inbox, queen beats — offline unit tests."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.websocket.cli_dual_coo import (  # noqa: E402
    RISK_GREEN,
    RISK_RED,
    RISK_YELLOW,
    classify_risk,
    dual_coo_system_addon,
)


class TestClassifyRisk(unittest.TestCase):
    def test_clinical_domain_red(self):
        self.assertEqual(classify_risk(domain="clinical"), RISK_RED)
        self.assertEqual(classify_risk(domain="defense"), RISK_RED)

    def test_therapeutic_path_red(self):
        self.assertEqual(
            classify_risk(files=["backend/app/services/nevedal_engine.py"]),
            RISK_RED,
        )
        self.assertEqual(
            classify_risk(files=["backend/app/services/sensitive_clinical_bridge.py"]),
            RISK_RED,
        )

    def test_review_green(self):
        self.assertEqual(
            classify_risk(kind="review", files=["backend/app/services/token_lab_auditor.py"]),
            RISK_GREEN,
        )

    def test_patent_and_prior_art_green(self):
        self.assertEqual(
            classify_risk(kind="patent_tag_propose", files=["foo.py"]),
            RISK_GREEN,
        )
        self.assertEqual(classify_risk(kind="prior_art_flag"), RISK_GREEN)
        self.assertEqual(classify_risk(kind="patent_crystal_tag"), RISK_GREEN)
        self.assertEqual(classify_risk(kind="matching_weight"), RISK_GREEN)
        self.assertEqual(classify_risk(kind="brief_refine"), RISK_GREEN)

    def test_coo_addon_mentions_ceo(self):
        text = dual_coo_system_addon()
        self.assertIn("CEO", text)
        self.assertIn("GREEN", text)
        self.assertIn("RED", text)


class TestCeoInbox(unittest.TestCase):
    def test_enqueue_skipped_for_green(self):
        from app.websocket.cli_dual_coo import enqueue_ceo

        r = enqueue_ceo(risk=RISK_GREEN, title="x")
        self.assertEqual(r.get("status"), "skipped")

    @patch("app.websocket.cli_dual_coo._redis")
    def test_enqueue_yellow(self, mock_redis):
        from app.websocket.cli_dual_coo import enqueue_ceo

        client = MagicMock()
        client.get.return_value = None
        client.set.return_value = True
        mock_redis.return_value = client
        r = enqueue_ceo(risk=RISK_YELLOW, title="batch me", detail="d", origin="cloud")
        self.assertEqual(r.get("status"), "ok")
        client.lpush.assert_called()

    def test_uuid_task_ids_collapse_when_kind_present(self):
        from app.websocket.cli_dual_coo import ceo_issue_fingerprint

        pl = {
            "kind": "trust_reprobe",
            "auditor": "Defense Health",
            "category": "DEFENSE_DEGRADED",
        }
        a = ceo_issue_fingerprint(
            title="Trust RED: Defense Health (DEFENSE_DEGRADED)",
            origin="cloud",
            task_id="a1b2c3d4e5f67890",
            payload=pl,
        )
        b = ceo_issue_fingerprint(
            title="Trust RED: Defense Health (DEFENSE_DEGRADED) [#ceo31e30abc]",
            origin="cloud",
            task_id="ffffffffffffffff",
            payload=pl,
        )
        self.assertEqual(a, b)

    def test_distinct_kinds_do_not_collapse(self):
        from app.websocket.cli_dual_coo import ceo_issue_fingerprint

        a = ceo_issue_fingerprint(
            title="Growth segment propose",
            origin="growth",
            payload={"kind": "growth_segment_propose"},
        )
        b = ceo_issue_fingerprint(
            title="Growth weekly digest — 0 stale reviews",
            origin="growth",
            payload={"kind": "growth_weekly_digest"},
        )
        self.assertNotEqual(a, b)

    @patch("app.websocket.cli_dual_coo._redis")
    def test_enqueue_skips_when_suppressed(self, mock_redis):
        from app.websocket.cli_dual_coo import enqueue_ceo

        client = MagicMock()
        client.get.return_value = b"1"
        mock_redis.return_value = client
        r = enqueue_ceo(
            risk=RISK_YELLOW,
            title="Clinical bakeoff yield below floor",
            payload={"kind": "nate_clinical_revision_candidate"},
        )
        self.assertEqual(r.get("status"), "skipped")
        self.assertEqual(r.get("reason"), "suppressed")
        client.lpush.assert_not_called()

    @patch("app.websocket.cli_dual_coo._redis")
    def test_enqueue_skips_dedup(self, mock_redis):
        from app.websocket.cli_dual_coo import enqueue_ceo

        client = MagicMock()
        client.get.return_value = None
        client.set.return_value = None
        mock_redis.return_value = client
        r = enqueue_ceo(risk=RISK_YELLOW, title="Growth segment propose")
        self.assertEqual(r.get("status"), "skipped")
        self.assertEqual(r.get("reason"), "dedup")
        client.lpush.assert_not_called()

    @patch("app.websocket.cli_dual_coo._redis")
    def test_mark_ceo_issue_decided_sets_suppress(self, mock_redis):
        from app.websocket.cli_dual_coo import mark_ceo_issue_decided

        client = MagicMock()
        mock_redis.return_value = client
        self.assertTrue(mark_ceo_issue_decided("abc123", ttl_s=3600))
        client.set.assert_called()
        args, kwargs = client.set.call_args
        self.assertIn("cli:ceo_suppress:abc123", args[0])
        self.assertEqual(kwargs.get("ex"), 3600)


class TestCrystalApplyDomains(unittest.TestCase):
    def test_red_domains_blocked(self):
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "services"
            / "crystal_outcome_apply.py"
        ).read_text(encoding="utf-8")
        self.assertIn('RED_DOMAINS = frozenset({"clinical", "defense"})', src)
        self.assertIn('"coding"', src)
        self.assertIn('"patent"', src)
        self.assertIn("UPDATE nate_intelligence_crystals", src)


class TestShadowInvariantPreserved(unittest.TestCase):
    def test_db_maintenance_source_file_has_no_live_update(self):
        """Scan source text without importing heavy nevedal deps."""
        import re
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / "app" / "services" / "db_maintenance_agent.py"
        source = path.read_text(encoding="utf-8")
        pattern = re.compile(r"UPDATE\s+nate_intelligence_crystals", re.IGNORECASE)
        self.assertEqual(pattern.findall(source), [])
        apply_path = Path(__file__).resolve().parents[1] / "app" / "services" / "crystal_outcome_apply.py"
        apply_src = apply_path.read_text(encoding="utf-8")
        self.assertIn("UPDATE nate_intelligence_crystals", apply_src)


if __name__ == "__main__":
    unittest.main()
