"""Offline tests for Dual-COO loop closer, auditor dispatch, Sovereign Standard gate."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestClassifyRiskExtended(unittest.TestCase):
    def test_compliance_green(self):
        from app.websocket.cli_dual_coo import RISK_GREEN, classify_risk

        self.assertEqual(
            classify_risk(kind="compliance_redteam", files=["a.py"]),
            RISK_GREEN,
        )

    def test_insight_route_yellow(self):
        from app.websocket.cli_dual_coo import RISK_YELLOW, classify_risk

        self.assertEqual(classify_risk(kind="insight_route"), RISK_YELLOW)
        self.assertEqual(classify_risk(kind="coach_label"), RISK_YELLOW)

    def test_ops_fix_green(self):
        from app.websocket.cli_dual_coo import RISK_GREEN, classify_risk

        self.assertEqual(classify_risk(kind="ops_fix"), RISK_GREEN)


class TestAuditorBusDispatch(unittest.TestCase):
    def test_dispatch_module_source(self):
        """Avoid importing redis-heavy bus at collection time — source contract."""
        src = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "services"
            / "auditor_bus_dispatch.py"
        ).read_text(encoding="utf-8")
        self.assertIn("dispatch_enforcement_actions", src)
        self.assertIn("ops_fix", src)
        self.assertIn("publish_task", src)


class TestSovereignStandardGate(unittest.TestCase):
    def test_gate_source_contract(self):
        src = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "services"
            / "sovereign_standard_gate.py"
        ).read_text(encoding="utf-8")
        self.assertIn("def therapeutic_module", src)
        self.assertIn("def scan_therapeutic_sources", src)
        self.assertIn("def ci_gate_pass", src)
        self.assertIn("THERAPEUTIC_MARKERS", src)


class TestCeoInboxAck(unittest.TestCase):
    @patch("app.websocket.cli_dual_coo._redis")
    def test_ack_all(self, mock_redis):
        from app.websocket.cli_dual_coo import ack_ceo_inbox

        client = MagicMock()
        client.llen.return_value = 3
        mock_redis.return_value = client
        r = ack_ceo_inbox(ack_all=True)
        self.assertEqual(r.get("status"), "ok")
        client.delete.assert_called()


class TestFailover(unittest.TestCase):
    @patch("app.websocket.cli_dual_coo._redis")
    def test_set_failover(self, mock_redis):
        from app.websocket.cli_dual_coo import (
            cloud_sole_failover_active,
            set_cloud_sole_failover,
        )

        client = MagicMock()
        client.get.return_value = '{"active": true}'
        mock_redis.return_value = client
        self.assertTrue(set_cloud_sole_failover(True))
        self.assertTrue(cloud_sole_failover_active())


class TestPatentSweepPresent(unittest.TestCase):
    def test_sweep_in_source(self):
        src = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "services"
            / "patent_claim_guardian.py"
        ).read_text(encoding="utf-8")
        self.assertIn("async def sweep_patent_crystals", src)
        self.assertIn("async def propose_claim_tag", src)


class TestCrystalApplyCeoClinical(unittest.TestCase):
    def test_ceo_apply_in_source(self):
        src = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "services"
            / "crystal_outcome_apply.py"
        ).read_text(encoding="utf-8")
        self.assertIn("async def ceo_apply_clinical_shadows", src)
        self.assertIn("ceo_clinical_apply_approvals", src)
        self.assertIn("'RED'", src)


class TestMigration244Present(unittest.TestCase):
    def test_migration_file(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "244_dual_coo_loop_closer.sql"
        )
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        self.assertIn("coach_insight_briefs", text)
        self.assertIn("prior_art_sweep_log", text)
        self.assertIn("ceo_clinical_apply_approvals", text)


class TestCeoApiRouterSource(unittest.TestCase):
    def test_router_endpoints(self):
        src = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "routers"
            / "ceo_dual_coo_api.py"
        ).read_text(encoding="utf-8")
        for marker in (
            "/inbox",
            "/patent-tags/approve",
            "/clinical-apply",
            "/loop-status",
            "require_admin",
        ):
            self.assertIn(marker, src)


class TestLoopCloserSource(unittest.TestCase):
    def test_closer_cycles_present(self):
        src = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "services"
            / "dual_coo_loop_closer.py"
        ).read_text(encoding="utf-8")
        for marker in (
            "_cycle_coach_labels",
            "_cycle_insight_briefs",
            "_cycle_compliance_redteam",
            "_cycle_prior_art",
            "_cycle_second_order",
            "_cycle_peer_failover",
        ):
            self.assertIn(marker, src)


if __name__ == "__main__":
    unittest.main()
