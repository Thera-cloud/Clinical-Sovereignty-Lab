"""Offline tests — CEO Phase A+B remediation kinds + briefs.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class TestFuelAndTrustBriefs(unittest.TestCase):
    def test_fuel_stall_brief_says_burst_on_approve(self):
        from app.services.ceo_inbox_notify import build_ceo_review_brief

        brief = build_ceo_review_brief(
            {
                "risk": "YELLOW",
                "title": "[FUEL STALLED] coding flat at 84 for 3d",
                "detail": "coding: 84/300",
                "origin": "ln7_fuel_gauge",
                "payload": {
                    "kind": "ln7_fuel_volume_burst",
                    "domain": "coding",
                    "ask_of_ceo": "APPROVE to run fuel burst",
                },
            }
        )
        bl = (brief.get("bottom_line") or "").lower()
        self.assertIn("fuel burst", bl)
        self.assertIn("approve", bl)
        self.assertNotIn("ack only", bl)

    def test_trust_red_brief_says_reprobe(self):
        from app.services.ceo_inbox_notify import build_ceo_review_brief

        brief = build_ceo_review_brief(
            {
                "risk": "RED",
                "title": "Trust RED: Defense Health (ENDPOINT_DOWN)",
                "detail": "6/8 TRUSTED",
                "payload": {
                    "kind": "trust_reprobe",
                    "auditor": "Defense Health",
                    "category": "ENDPOINT_DOWN",
                },
            }
        )
        bl = (brief.get("bottom_line") or "").lower()
        self.assertIn("reprobe", bl)
        impact = (brief.get("expected_impact") or "").lower()
        self.assertIn("re-run", impact)


class TestRemediationDispatch(unittest.TestCase):
    def test_unknown_kind_skipped(self):
        from app.services.ceo_remediation_apply import apply_ceo_remediation

        out = asyncio.get_event_loop().run_until_complete(
            apply_ceo_remediation(None, {"kind": "growth_content_review"})
        )
        self.assertTrue(out.get("skipped"))
        self.assertEqual(out.get("reason"), "not_remediation_kind")

    def test_fuel_cooldown_skips_burst(self):
        from app.services import ceo_remediation_apply as mod

        fake_redis = MagicMock()
        fake_redis.get.return_value = b"ceo_prior"

        async def _run():
            with patch.object(mod, "_redis", return_value=fake_redis):
                with patch.object(mod, "_collect_smoke", new=AsyncMock(return_value={"checks": [], "all_ok": True})):
                    with patch.object(mod, "_fallback_llm_reflect", new=AsyncMock(return_value={"ok": False})):
                        with patch.object(mod, "_log_remediation", new=AsyncMock()):
                            return await mod.apply_ceo_remediation(
                                MagicMock(),
                                {"kind": "ln7_fuel_volume_burst", "domain": "coding"},
                            )

        out = asyncio.get_event_loop().run_until_complete(_run())
        self.assertFalse(out.get("ok"))
        self.assertEqual(out["execution"].get("reason"), "cooldown_12h")
        self.assertIn("cooldown", (out.get("summary_text") or "").lower())

    def test_apply_ceo_payload_routes_remediation(self):
        from app.services import ceo_inbox_notify as cin

        async def _run():
            with patch(
                "app.services.ceo_remediation_apply.apply_ceo_remediation",
                new=AsyncMock(return_value={"ok": True, "kind": "trust_reprobe", "summary_text": "ok"}),
            ) as mocked:
                out = await cin._apply_ceo_payload(
                    MagicMock(),
                    {"kind": "trust_reprobe", "auditor": "Defense Health"},
                    approved_by="test",
                )
                mocked.assert_awaited_once()
                return out

        out = asyncio.get_event_loop().run_until_complete(_run())
        self.assertEqual(out["remediation"]["kind"], "trust_reprobe")

    def test_confirmation_appends_summary(self):
        from app.services.approval_protocol import ApprovalProtocolService

        proto = ApprovalProtocolService.__new__(ApprovalProtocolService)
        _subj, body = proto._build_decision_confirmation(
            {"title": "Trust RED: Defense Health", "proposal_id": "p1"},
            "APPROVE",
            "email",
            apply_summary="Reprobe: 8/8 TRUSTED\nSmoke OK",
        )
        self.assertIn("Execution report", body)
        self.assertIn("8/8 TRUSTED", body)
        self.assertIn("Allowlisted remediation", body)


if __name__ == "__main__":
    unittest.main()
