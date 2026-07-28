"""Offline tests — Dual-COO CEO decision briefs + LN7 readiness framing.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class TestCeoDecisionBriefSchema(unittest.TestCase):
    def test_summary_block_has_decision_headers(self):
        from app.services.ceo_inbox_notify import build_ceo_review_brief

        brief = build_ceo_review_brief(
            {
                "risk": "YELLOW",
                "title": "Generic Dual-COO item",
                "detail": "something happened",
                "origin": "cloud",
                "payload": {},
            }
        )
        block = brief["summary_block"]
        self.assertIn("=== WHAT HAPPENED", block)
        self.assertIn("=== WHAT IT SHOULD DO ===", block)
        self.assertIn("=== WHAT IT SHOULD NOT BE ===", block)
        self.assertIn("=== BOTTOM LINE ===", block)
        self.assertIn("=== WHAT I NEED FROM YOU ===", block)
        self.assertTrue(brief.get("what_it_should_do"))
        self.assertTrue(brief.get("what_it_should_not_be"))
        self.assertTrue(brief.get("bottom_line"))

    def test_attach_persists_fields_on_payload(self):
        from app.services.ceo_brief_schema import attach_ceo_brief_to_item, payload_has_decision_brief

        item = {
            "risk": "RED",
            "title": "Trust RED: Billing (AUTH_FAILURE)",
            "detail": "token missing",
            "payload": {"category": "AUTH_FAILURE", "auditor": "Billing"},
        }
        out = attach_ceo_brief_to_item(item)
        self.assertTrue(payload_has_decision_brief(out["payload"]))
        self.assertIn("what_it_should_do", out["brief"])
        self.assertTrue(out["brief"]["bottom_line"])


class TestLn7RevisionBriefs(unittest.TestCase):
    def test_premature_yellow_hold(self):
        from app.services.ceo_inbox_notify import build_ceo_review_brief

        brief = build_ceo_review_brief(
            {
                "risk": "YELLOW",
                "title": "LN7 revision candidate: LN7-2026-07-28T054529Z [HOLD]",
                "detail": "HOLD — premature",
                "origin": "ln7",
                "payload": {
                    "kind": "ln7_revision_candidate",
                    "revision_id": "LN7-2026-07-28T054529Z",
                    "ready": False,
                    "readiness": {
                        "ready": False,
                        "reason": "insufficient_private_pack_outcomes",
                        "checks": {
                            "model_card": True,
                            "adapter_path": False,
                            "peft_probe": False,
                            "private_pack_n": 0,
                            "canary_ready": False,
                            "canary_status": "none",
                        },
                    },
                    "apply": {"action": "none", "kind": "ln7_hold"},
                },
            }
        )
        self.assertIn("HOLD", brief["bottom_line"].upper())
        self.assertIn("WHAT IT SHOULD DO", brief["summary_block"])
        self.assertTrue(
            any("not" in str(x).lower() or "HOLD" in str(x) for x in brief["what_it_should_do"])
            or "premature" in brief["bottom_line"].lower()
            or "HOLD" in brief["bottom_line"]
        )
        joined_not = " ".join(brief["what_it_should_not_be"]).lower()
        self.assertTrue("agi" in joined_not or "activate" in joined_not)

    def test_ready_red_activate_language(self):
        from app.services.ceo_inbox_notify import build_ceo_review_brief

        brief = build_ceo_review_brief(
            {
                "risk": "RED",
                "title": "LN7 revision candidate: LN7-2026-07-28T120000Z [READY]",
                "detail": "APPROVE to activate",
                "origin": "ln7",
                "payload": {
                    "kind": "ln7_revision_candidate",
                    "revision_id": "LN7-2026-07-28T120000Z",
                    "ready": True,
                    "readiness": {
                        "ready": True,
                        "reason": "ready_for_ceo_activate",
                        "checks": {
                            "model_card": True,
                            "adapter_path": True,
                            "peft_probe": True,
                            "private_pack_n": 5,
                            "canary_ready": True,
                            "canary_status": "active",
                        },
                        "adapter_path": "/opt/ln7/adapters/x",
                        "base_checkpoint": "qwen2.5-coder:14b",
                    },
                    "apply": {
                        "action": "activate",
                        "kind": "ln7_activate",
                        "revision_id": "LN7-2026-07-28T120000Z",
                    },
                },
            }
        )
        self.assertIn("APPROVE", brief["bottom_line"])
        self.assertIn("activate", brief["bottom_line"].lower())
        joined_do = " ".join(brief["what_it_should_do"]).lower()
        self.assertIn("activate", joined_do)
        joined_not = " ".join(brief["what_it_should_not_be"]).lower()
        self.assertIn("agi", joined_not)


class TestLn7ApplyOnApprove(unittest.IsolatedAsyncioTestCase):
    async def test_apply_skips_when_not_ready(self):
        from app.services.ceo_inbox_notify import _apply_ceo_payload

        out = await _apply_ceo_payload(
            None,
            {
                "kind": "ln7_revision_candidate",
                "ready": False,
                "revision_id": "LN7-x",
                "apply": {"action": "none"},
            },
            approved_by="ceo",
        )
        self.assertTrue(out["ln7_revision"].get("skipped"))

    async def test_apply_activates_when_ready(self):
        from app.services.ceo_inbox_notify import _apply_ceo_payload

        with patch(
            "app.services.ln7_revision.activate_revision",
            new_callable=AsyncMock,
            return_value={"ok": True, "revision_id": "LN7-ready", "active": True},
        ) as act:
            out = await _apply_ceo_payload(
                MagicMock(),
                {
                    "kind": "ln7_revision_candidate",
                    "ready": True,
                    "revision_id": "LN7-ready",
                    "apply": {
                        "action": "activate",
                        "revision_id": "LN7-ready",
                        "kind": "ln7_activate",
                    },
                },
                approved_by="DrNevedal1",
            )
            act.assert_awaited_once()
            self.assertTrue(out["ln7_revision"].get("ok"))


class TestReadinessNoDb(unittest.IsolatedAsyncioTestCase):
    async def test_no_db_is_premature(self):
        from app.services.ln7_revision_readiness import assess_revision_readiness

        r = await assess_revision_readiness(None, "LN7-2026-07-28T054529Z")
        self.assertFalse(r["ready"])
        self.assertEqual(r["reason"], "no_db")
        self.assertEqual(r["readiness_class"], "premature")


if __name__ == "__main__":
    unittest.main()
