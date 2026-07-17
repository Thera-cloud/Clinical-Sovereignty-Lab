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

    def test_patent_foundation_yellow(self):
        self.assertEqual(
            classify_risk(kind="patent_tag_propose", files=["foo.py"]),
            RISK_YELLOW,
        )

    def test_patent_crystal_and_sandbox_green(self):
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
        mock_redis.return_value = client
        r = enqueue_ceo(risk=RISK_YELLOW, title="batch me", detail="d", origin="cloud")
        self.assertEqual(r.get("status"), "ok")
        client.lpush.assert_called()


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
