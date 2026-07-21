#!/usr/bin/env python3
"""Compatibility wrapper — prefer clinical_tier1_competence_gate_check.py."""

from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    target = Path(__file__).with_name("clinical_tier1_competence_gate_check.py")
    runpy.run_path(str(target), run_name="__main__")
