"""Offline seams for D.13 flywheel acceleration (importlib — avoid numpy)."""

from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"


def _load(name: str, path: Path):
    if "app" not in sys.modules:
        sys.modules["app"] = types.ModuleType("app")
    if "app.services" not in sys.modules:
        pkg = types.ModuleType("app.services")
        pkg.__path__ = [str(APP / "services")]  # type: ignore[attr-defined]
        sys.modules["app.services"] = pkg
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_accel = _load(
    "app.services.six_quotient_acceleration",
    APP / "services" / "six_quotient_acceleration.py",
)
_aud = _load(
    "app.services.six_quotient_battery_auditor",
    APP / "services" / "six_quotient_battery_auditor.py",
)


class TestBrier(unittest.TestCase):
    def test_perfect_calibration(self):
        pairs = [(1.0, 1.0), (0.0, 0.0), (1.0, 1.0)]
        self.assertEqual(_accel.brier_score(pairs), 0.0)

    def test_worst_calibration(self):
        pairs = [(1.0, 0.0), (0.0, 1.0)]
        self.assertEqual(_accel.brier_score(pairs), 1.0)

    def test_empty_none(self):
        self.assertIsNone(_accel.brier_score([]))


class TestPearson(unittest.TestCase):
    def test_perfect_positive(self):
        xs = [1.0, 2.0, 3.0, 4.0]
        ys = [2.0, 4.0, 6.0, 8.0]
        self.assertAlmostEqual(_accel.pearson(xs, ys) or 0, 1.0, places=3)

    def test_sparse_none(self):
        self.assertIsNone(_accel.pearson([1.0], [2.0]))


class TestPmbSeeds(unittest.TestCase):
    def test_privacy_floor(self):
        seeds = _accel.pmb_seed_from_domains(
            [{"domain": "addiction", "n_clients": 3, "avg_confidence": 0.7}]
        )
        self.assertEqual(seeds, [])

    def test_maps_domain_to_section(self):
        seeds = _accel.pmb_seed_from_domains(
            [{"domain": "addiction", "n_clients": 8, "avg_confidence": 0.6}]
        )
        self.assertEqual(len(seeds), 1)
        self.assertEqual(seeds[0]["section"], "AQ")
        self.assertEqual(seeds[0]["source"], "pmb_mined")
        self.assertEqual(seeds[0]["status"], "pending_review")
        self.assertNotIn("user_id", seeds[0])
        self.assertNotIn("username", str(seeds[0]))


class TestAccelerationFlag(unittest.IsolatedAsyncioTestCase):
    async def test_flag_off_skips(self):
        with patch.dict(os.environ, {"ENABLE_SIX_QUOTIENT_ACCELERATION": "false"}, clear=False):
            out = await _accel.run_acceleration_pass(None, mine_pmb=False)
        self.assertTrue(out.get("skipped"))
        self.assertIn("off", str(out.get("error") or ""))


class TestAuditorEighteen(unittest.TestCase):
    def test_eighteen_checks(self):
        total = sum(len(t["endpoints"]) for t in _aud.TAB_ENDPOINTS)
        self.assertEqual(total, 18)
        flat = [ep for t in _aud.TAB_ENDPOINTS for ep in t["endpoints"]]
        self.assertIn(("GET", "/api/admin/six-quotient/acceleration"), flat)


if __name__ == "__main__":
    unittest.main()
