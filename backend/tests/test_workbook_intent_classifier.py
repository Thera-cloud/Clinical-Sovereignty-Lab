"""Offline tests for workbook_intent_classifier + ln_response_stance + planner."""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import ln_response_stance  # noqa: E402
from app.services.workbook_intent_classifier import (  # noqa: E402
    IntentResult,
    classify,
    suggested_offer_line,
)
from app.services.workbook_coaching_planner import plan_for_user  # noqa: E402


CATALOG = [
    "Gestalts Steps.pdf",
    "IFS Parts Map.pdf",
    "EFT-SM Protocol.pdf",
    "Polyvagal Reset.txt",
    "Boundary Stabilization.md",
]


class TestClassifier(unittest.TestCase):
    def test_empty_returns_none(self):
        r = classify("")
        self.assertEqual(r.method, "none")
        self.assertEqual(r.action, "observe")
        self.assertEqual(r.confidence, 0.0)

    def test_gestalt_offer_with_workbook(self):
        r = classify(
            "There's unfinished business with my dad. I keep imagining what I'd say if they were sitting here.",
            catalog=CATALOG,
        )
        self.assertEqual(r.method, "gestalt")
        self.assertEqual(r.action, "offer")
        self.assertEqual(r.workbook_file, "Gestalts Steps.pdf")
        self.assertGreaterEqual(r.confidence, 0.55)
        self.assertIn("gestalt", r.rationale.lower())

    def test_ifs_offer(self):
        r = classify(
            "A part of me wants to leave and another part is terrified. Younger part keeps pulling me back.",
            catalog=CATALOG,
        )
        self.assertEqual(r.method, "ifs")
        self.assertEqual(r.action, "offer")

    def test_eft_offer(self):
        r = classify(
            "We keep having the same fight. I pursue and she withdraws every single night.",
            catalog=CATALOG,
        )
        self.assertEqual(r.method, "eft")
        self.assertEqual(r.action, "offer")

    def test_polyvagal_offer(self):
        r = classify(
            "I feel like I'm shutting down. Can't breathe, heart racing, nervous system fried.",
            catalog=CATALOG,
        )
        self.assertEqual(r.method, "polyvagal")
        self.assertIn(r.action, ("offer", "observe"))
        # at least it should surface the method
        self.assertGreater(r.confidence, 0.0)

    def test_boundary_offer(self):
        r = classify(
            "My mother keeps pushing and I can't say no. I feel guilty for saying no.",
            catalog=CATALOG,
        )
        self.assertEqual(r.method, "boundary_stabilization")
        self.assertEqual(r.action, "offer")

    def test_frame_control_downgrades_to_observe(self):
        r = classify(
            "Stop asking me about feelings. We keep having the same fight and I pursue and she withdraws — "
            "just give me actionable strategies.",
            catalog=CATALOG,
        )
        # method matches (eft) but frame-control forces observe
        self.assertEqual(r.method, "eft")
        self.assertEqual(r.action, "observe")
        self.assertIn("frame_control", r.rationale)

    def test_skill_plan_lock_defers(self):
        r = classify(
            "I keep having the same fight, pursue and withdraw.",
            skill_plan_locked=True,
            catalog=CATALOG,
        )
        self.assertEqual(r.action, "defer")

    def test_explicit_tool_request_boosts_confidence(self):
        r = classify("Give me a tool for grounding right now", catalog=CATALOG)
        self.assertGreaterEqual(r.confidence, 0.35)  # request itself doesn't create a match

    def test_recent_history_boosts_signal(self):
        r = classify(
            "It happened again last night",
            recent_texts=[
                "we keep fighting",
                "I pursue and she withdraws",
            ],
            catalog=CATALOG,
        )
        self.assertEqual(r.method, "eft")

    def test_suggested_offer_line_shape(self):
        r = classify(
            "There's unfinished business with my dad and I keep imagining if they were sitting across from me.",
            catalog=CATALOG,
        )
        line = suggested_offer_line(r)
        self.assertIn("empty-chair", line.lower())
        self.assertIn("Gestalts Steps.pdf", line)

    def test_to_dict(self):
        r = classify("empty chair for my father", catalog=CATALOG)
        d = r.to_dict()
        for k in ("method", "workbook_file", "confidence", "action", "rationale", "signals"):
            self.assertIn(k, d)


class TestStanceBlock(unittest.TestCase):
    def setUp(self):
        os.environ["ENABLE_LN_ASSERTIVE_STANCE"] = "true"

    def test_enabled_flag_defaults_on(self):
        os.environ.pop("ENABLE_LN_ASSERTIVE_STANCE", None)
        self.assertTrue(ln_response_stance.is_enabled())

    def test_disabled_returns_empty(self):
        os.environ["ENABLE_LN_ASSERTIVE_STANCE"] = "false"
        self.assertEqual(ln_response_stance.stance_block(None), "")

    def test_none_intent(self):
        os.environ["ENABLE_LN_ASSERTIVE_STANCE"] = "true"
        block = ln_response_stance.stance_block(None)
        self.assertIn("MAX ONE reflection question", block)
        self.assertIn("no workbook match", block.lower())

    def test_offer_intent(self):
        os.environ["ENABLE_LN_ASSERTIVE_STANCE"] = "true"
        r = classify(
            "unfinished business with my mother, empty chair kind of stuff", catalog=CATALOG
        )
        block = ln_response_stance.stance_block(r)
        self.assertIn("action=OFFER", block)
        self.assertIn("empty-chair", block.lower())

    def test_defer_intent(self):
        os.environ["ENABLE_LN_ASSERTIVE_STANCE"] = "true"
        r = IntentResult(
            method="ifs", confidence=0.7, action="defer", rationale="skill_plan_locked"
        )
        block = ln_response_stance.stance_block(r)
        self.assertIn("action=DEFER", block)

    def test_observe_intent(self):
        os.environ["ENABLE_LN_ASSERTIVE_STANCE"] = "true"
        r = IntentResult(
            method="polyvagal", confidence=0.4, action="observe", rationale="weak match"
        )
        block = ln_response_stance.stance_block(r)
        self.assertIn("action=OBSERVE", block)
        self.assertIn("do not offer", block.lower())


class TestPlanner(unittest.TestCase):
    def test_plan_without_db_or_state(self):
        recent = [
            "we keep fighting, I pursue and she withdraws every night",
            "a part of me wants to leave and another part is terrified",
        ]

        async def _run():
            return await plan_for_user(None, None, "test_user", recent_texts=recent)

        plan = asyncio.get_event_loop().run_until_complete(_run())
        self.assertEqual(plan["hardware_id"], "test_user")
        self.assertGreaterEqual(len(plan["predicted_methods"]), 1)
        self.assertIn("foreshadow", plan)
        self.assertEqual(plan["self_reflection"]["past_offers"], 0)
        self.assertEqual(plan["self_reflection"]["estimated_influence"], "unknown")

    def test_plan_empty_input(self):
        async def _run():
            return await plan_for_user(None, None, "test_user", recent_texts=[])

        plan = asyncio.get_event_loop().run_until_complete(_run())
        self.assertEqual(plan["predicted_methods"], [])
        self.assertIn("observe", plan["foreshadow"].lower())


if __name__ == "__main__":
    unittest.main()
