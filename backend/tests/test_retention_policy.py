"""Unit tests for backend/app/services/retention_policy.py (Slice 1)."""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path


def _reload_module(env: dict):
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    if "app.services.retention_policy" in sys.modules:
        del sys.modules["app.services.retention_policy"]
    import app.services.retention_policy as mod
    return importlib.reload(mod)


def test_default_forever_when_settings_missing(tmp_path: Path):
    mod = _reload_module({"DATA_DIR": str(tmp_path)})
    assert mod.get_retention_days() is None
    assert mod.is_retention_enforcement_enabled() is False
    desc = mod.describe_policy()
    assert desc["policy_days"] is None
    assert desc["policy_label"] == "forever"
    assert desc["enforcement_enabled"] is False


def test_policy_1_year(tmp_path: Path):
    (tmp_path / "admin_settings.json").write_text(
        json.dumps({"memory_retention_policy": "1_year"})
    )
    mod = _reload_module({"DATA_DIR": str(tmp_path)})
    assert mod.get_retention_days() == 365


def test_policy_6_months(tmp_path: Path):
    (tmp_path / "admin_settings.json").write_text(
        json.dumps({"memory_retention_policy": "6_months"})
    )
    mod = _reload_module({"DATA_DIR": str(tmp_path)})
    assert mod.get_retention_days() == 180


def test_policy_invalid_falls_back_to_forever(tmp_path: Path):
    (tmp_path / "admin_settings.json").write_text(
        json.dumps({"memory_retention_policy": "weekly"})
    )
    mod = _reload_module({"DATA_DIR": str(tmp_path)})
    assert mod.get_retention_days() is None


def test_settings_corrupt_falls_back_to_forever(tmp_path: Path):
    (tmp_path / "admin_settings.json").write_text("{not json")
    mod = _reload_module({"DATA_DIR": str(tmp_path)})
    assert mod.get_retention_days() is None


def test_enforcement_flag_true(tmp_path: Path):
    mod = _reload_module(
        {
            "DATA_DIR": str(tmp_path),
            "ENABLE_RETENTION_ENFORCEMENT": "true",
        }
    )
    assert mod.is_retention_enforcement_enabled() is True


def test_enforcement_flag_off(tmp_path: Path):
    mod = _reload_module(
        {
            "DATA_DIR": str(tmp_path),
            "ENABLE_RETENTION_ENFORCEMENT": "no",
        }
    )
    assert mod.is_retention_enforcement_enabled() is False


def test_describe_policy_labels(tmp_path: Path):
    (tmp_path / "admin_settings.json").write_text(
        json.dumps({"memory_retention_policy": "1_year"})
    )
    mod = _reload_module(
        {
            "DATA_DIR": str(tmp_path),
            "ENABLE_RETENTION_ENFORCEMENT": "1",
        }
    )
    desc = mod.describe_policy()
    assert desc["policy_days"] == 365
    assert desc["policy_label"] == "365d"
    assert desc["enforcement_enabled"] is True


# ------------------------------------------------------------------ #
# Slice D-prep: 30_days policy + cohort-scoped per-user override.     #
# ------------------------------------------------------------------ #

def test_policy_30_days(tmp_path: Path):
    (tmp_path / "admin_settings.json").write_text(
        json.dumps({"memory_retention_policy": "30_days"})
    )
    mod = _reload_module({"DATA_DIR": str(tmp_path)})
    assert mod.get_retention_days() == 30


def test_cohort_user_gets_30_day_override_when_global_forever(tmp_path: Path):
    # Global policy is default "forever" (no settings file).
    mod = _reload_module({"DATA_DIR": str(tmp_path)})
    assert mod.get_retention_days() is None
    assert mod.get_retention_days_for_user("bee_hiv_plus") == 30


def test_cohort_user_takes_stricter_when_global_shorter(tmp_path: Path):
    (tmp_path / "admin_settings.json").write_text(
        json.dumps({"memory_retention_policy": "6_months"})  # 180d
    )
    mod = _reload_module({"DATA_DIR": str(tmp_path)})
    assert mod.get_retention_days() == 180
    # Cohort still gets 30 because min(180, 30) == 30.
    assert mod.get_retention_days_for_user("bee_hiv_plus") == 30


def test_non_cohort_user_uses_global(tmp_path: Path):
    (tmp_path / "admin_settings.json").write_text(
        json.dumps({"memory_retention_policy": "1_year"})
    )
    mod = _reload_module({"DATA_DIR": str(tmp_path)})
    assert mod.get_retention_days_for_user(None) == 365
    assert mod.get_retention_days_for_user("") == 365
    assert mod.get_retention_days_for_user("some_other_program") == 365


def test_cohort_case_insensitive(tmp_path: Path):
    mod = _reload_module({"DATA_DIR": str(tmp_path)})
    assert mod.get_retention_days_for_user("BEE_HIV_PLUS") == 30
    assert mod.get_retention_days_for_user(" bee_hiv_plus ") == 30


def test_describe_policy_exposes_strict_cohorts(tmp_path: Path):
    mod = _reload_module({"DATA_DIR": str(tmp_path)})
    desc = mod.describe_policy()
    assert "bee_hiv_plus" in desc["strict_cohorts"]
    assert desc["strict_default_days"] == 30
