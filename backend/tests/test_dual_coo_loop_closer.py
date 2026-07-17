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
        self.assertIn("_ALL_BUS_CATEGORIES", src)
        self.assertIn("ENDPOINT_DOWN", src)
        self.assertIn("DATA_PIPELINE", src)


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
            "liminal_presence_analysis",
            "pmb_report_requests",
            "dedupe_key",
        ):
            self.assertIn(marker, src)
        # Privacy: must not ILIKE-scan skyeye for shame / broad pmb audits
        self.assertNotIn("content ILIKE '%shame%'", src)
        self.assertNotIn("type ILIKE '%pmb%'", src)


class TestCeoEnqueueDedup(unittest.TestCase):
    @patch("app.websocket.cli_dual_coo._redis")
    def test_dedup_skips_repeat(self, mock_redis):
        from app.websocket.cli_dual_coo import enqueue_ceo

        client = MagicMock()
        client.set.return_value = None  # NX miss → already present
        mock_redis.return_value = client
        r = enqueue_ceo(risk="YELLOW", title="same", detail="x", origin="cloud")
        self.assertEqual(r.get("status"), "skipped")
        self.assertEqual(r.get("reason"), "dedup")


class TestOpsPassLogicSource(unittest.TestCase):
    def test_no_baseline_absent_pass(self):
        src = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "services"
            / "cli_task_bus_consumer.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn('"baseline" not in notes', src)
        self.assertIn("clean_markers", src)
        self.assertIn("auth_failure", src)


class TestMacFailoverClaim(unittest.TestCase):
    def test_claim_blocks_mac_on_cloud_sole(self):
        src = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "websocket"
            / "cli_task_bus.py"
        ).read_text(encoding="utf-8")
        self.assertIn("cloud_sole_failover_active", src)
        self.assertIn("cloud_sole_failover_mac_blocked", src)
        self.assertIn("failover_takeover", src)


class TestMacQueenBeatSource(unittest.TestCase):
    def test_mac_agent_queen_loop(self):
        src = (
            Path(__file__).resolve().parents[1]
            / "mac_agent"
            / "nate_mac_agent.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_dual_coo_queen_beat_loop", src)
        self.assertIn("beat_queen(", src)
        self.assertIn('"mac"', src)
        self.assertIn("mac_agent_loop", src)

    def test_loop_closer_probe(self):
        src = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "services"
            / "dual_coo_loop_closer.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_probe_mac_agent_and_beat", src)
        self.assertIn("_cycle_attribution_density", src)
        self.assertIn("google_patents_ingest", src)


class TestCeoDualCooAuditorSource(unittest.TestCase):
    def test_auditor_and_enforcer(self):
        aud = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "services"
            / "ceo_dual_coo_auditor.py"
        ).read_text(encoding="utf-8")
        self.assertIn("CeoDualCooAuditor", aud)
        self.assertIn("ceo_dual_coo_audit_sent", aud)
        enf = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "services"
            / "trust_enforcer.py"
        ).read_text(encoding="utf-8")
        self.assertIn("ceo_dual_coo_audit_sent", enf)
        self.assertIn("ceo_dual_coo_check_count", enf)


class TestGooglePatentsIngestSource(unittest.TestCase):
    def test_ingest_module(self):
        src = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "services"
            / "google_patents_ingest.py"
        ).read_text(encoding="utf-8")
        self.assertIn("async def search_google_patents", src)
        self.assertIn("async def ingest_patent_crystal_sweep", src)


class TestCoachOverrideRestSource(unittest.TestCase):
    def test_client_override_endpoint(self):
        src = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "routers"
            / "coach.py"
        ).read_text(encoding="utf-8")
        self.assertIn('@router.post("/client-override")', src)
        self.assertIn("crystallize_coach_observation", src)


class TestCiSovereignGateWired(unittest.TestCase):
    def test_run_ci_calls_gate(self):
        src = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "run_ci_tests.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("ci_gate_pass", src)
        self.assertIn("Sovereign Standard gate", src)


if __name__ == "__main__":
    unittest.main()
