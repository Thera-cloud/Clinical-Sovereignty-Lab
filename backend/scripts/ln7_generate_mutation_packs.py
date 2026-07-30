#!/usr/bin/env python3
"""LN7 mutation-task pack generator — grows ln7_tasks past 300 with source='mutation'.

QUANTUM-CRYSTAL-ARCH

Generates self-contained, self-verifying sandbox CI packs (same shape as the
hand-authored packs under backend/app/data/ln_sandbox_ci_packs/<name>/):

    <name>/broken/__init__.py
    <name>/broken/<module>.py   (buggy function)
    <name>/tests/__init__.py
    <name>/tests/test_<module>.py  (real behavioral assertions, not text-matching)
    <name>/golden.patch         (unified diff broken -> fixed)
    <name>/task.json            (task_key, title, prompt, test_path, target_files, domain)

Each pack is generated from a template covering a distinct, realistic bug class
(off-by-one, operator flip, mutable default arg, swapped args, wrong exception
type, etc.) so the resulting corpus teaches genuinely different repair skills,
not 16 copies of the same fix.

Self-verification (mandatory, no pack ships without passing both checks):
    1. pytest against the BROKEN tree must FAIL.
    2. golden.patch applied via the *actual* runtime unified-diff applier
       (ln_sandbox_engineering_ci.apply_unified_diff) must then make pytest PASS.

Usage:
    python3 backend/scripts/ln7_generate_mutation_packs.py \
        --out-dir backend/app/data/ln_sandbox_ci_packs \
        --sql-out backend/migrations/295_ln7_mutation_packs.sql \
        --index-out /tmp/ln7_mutation_index_patch.json
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Mutation templates. Each entry is a distinct, realistic bug class with a
# REAL behavioral test (calls the function, asserts on actual output) rather
# than a text-similarity judge — stronger training/eval signal.
# ---------------------------------------------------------------------------
TEMPLATES: List[Dict[str, Any]] = [
    {
        "name": "mut_off_by_one_range",
        "module": "ranges",
        "split": "heldout",
        "title": "Fix off-by-one in cumulative sum",
        "broken": (
            "def sum_first_n(n: int) -> int:\n"
            "    # BUG: off-by-one — excludes the nth term\n"
            "    total = 0\n"
            "    for i in range(1, n):\n"
            "        total += i\n"
            "    return total\n"
        ),
        "golden": (
            "def sum_first_n(n: int) -> int:\n"
            "    # Fixed: inclusive of the nth term\n"
            "    total = 0\n"
            "    for i in range(1, n + 1):\n"
            "        total += i\n"
            "    return total\n"
        ),
        "test": (
            "from broken.ranges import sum_first_n\n\n\n"
            "def test_sum_first_n():\n"
            "    assert sum_first_n(1) == 1\n"
            "    assert sum_first_n(5) == 15\n"
            "    assert sum_first_n(10) == 55\n"
        ),
        "prompt": (
            "The file broken/ranges.py has an off-by-one bug in sum_first_n: it "
            "excludes n itself from the running total. Fix ONLY the range() bound "
            "so sum_first_n(n) returns 1+2+...+n inclusive. Return ONLY a unified "
            "diff (---/+++ @@) for broken/ranges.py. No markdown fences."
        ),
    },
    {
        "name": "mut_and_or_swap",
        "module": "validators",
        "split": "train",
        "title": "Fix boolean operator swap (and/or)",
        "broken": (
            "def is_valid_age(age: int) -> bool:\n"
            "    # BUG: should require BOTH bounds, uses 'or' instead of 'and'\n"
            "    return age >= 0 or age <= 120\n"
        ),
        "golden": (
            "def is_valid_age(age: int) -> bool:\n"
            "    # Fixed: both bounds must hold\n"
            "    return age >= 0 and age <= 120\n"
        ),
        "test": (
            "from broken.validators import is_valid_age\n\n\n"
            "def test_is_valid_age():\n"
            "    assert is_valid_age(30) is True\n"
            "    assert is_valid_age(-5) is False\n"
            "    assert is_valid_age(200) is False\n"
        ),
        "prompt": (
            "The file broken/validators.py has is_valid_age using 'or' where both "
            "bounds must hold. Change ONLY the boolean operator to 'and'. Return "
            "ONLY a unified diff (---/+++ @@) for broken/validators.py. No markdown fences."
        ),
    },
    {
        "name": "mut_wrong_index",
        "module": "lists",
        "split": "train",
        "title": "Fix wrong index for last element",
        "broken": (
            "def last_element(items: list):\n"
            "    # BUG: returns the first element, not the last\n"
            "    return items[0]\n"
        ),
        "golden": (
            "def last_element(items: list):\n"
            "    # Fixed: return the last element\n"
            "    return items[-1]\n"
        ),
        "test": (
            "from broken.lists import last_element\n\n\n"
            "def test_last_element():\n"
            "    assert last_element([1, 2, 3]) == 3\n"
            "    assert last_element(['a', 'b']) == 'b'\n"
        ),
        "prompt": (
            "The file broken/lists.py has last_element returning items[0] instead "
            "of the final element. Fix ONLY the index. Return ONLY a unified diff "
            "(---/+++ @@) for broken/lists.py. No markdown fences."
        ),
    },
    {
        "name": "mut_integer_division",
        "module": "stats",
        "split": "train",
        "title": "Fix accidental integer division in average",
        "broken": (
            "def average(a: float, b: float) -> float:\n"
            "    # BUG: floor division truncates the result\n"
            "    return (a + b) // 2\n"
        ),
        "golden": (
            "def average(a: float, b: float) -> float:\n"
            "    # Fixed: true division preserves fractional average\n"
            "    return (a + b) / 2\n"
        ),
        "test": (
            "from broken.stats import average\n\n\n"
            "def test_average():\n"
            "    assert average(3, 4) == 3.5\n"
            "    assert average(10, 10) == 10\n"
        ),
        "prompt": (
            "The file broken/stats.py computes average using floor division '//' "
            "which truncates fractional results. Change ONLY the operator to '/'. "
            "Return ONLY a unified diff (---/+++ @@) for broken/stats.py. No markdown fences."
        ),
    },
    {
        "name": "mut_mutable_default_arg",
        "module": "collector",
        "split": "heldout",
        "title": "Fix classic mutable default argument bug",
        "broken": (
            "def append_item(item, items=[]):\n"
            "    # BUG: mutable default arg is shared across calls\n"
            "    items.append(item)\n"
            "    return items\n"
        ),
        "golden": (
            "def append_item(item, items=None):\n"
            "    # Fixed: fresh list per call\n"
            "    if items is None:\n"
            "        items = []\n"
            "    items.append(item)\n"
            "    return items\n"
        ),
        "test": (
            "from broken.collector import append_item\n\n\n"
            "def test_append_item_no_shared_state():\n"
            "    first = append_item(1)\n"
            "    second = append_item(2)\n"
            "    assert first == [1]\n"
            "    assert second == [2]\n"
        ),
        "prompt": (
            "The file broken/collector.py has a classic Python mutable-default-"
            "argument bug in append_item: the default list is shared across calls. "
            "Fix it using the None-sentinel pattern. Return ONLY a unified diff "
            "(---/+++ @@) for broken/collector.py. No markdown fences."
        ),
    },
    {
        "name": "mut_dict_get_default",
        "module": "config",
        "split": "train",
        "title": "Fix KeyError from direct dict indexing",
        "broken": (
            "def get_setting(cfg: dict, key: str, default=None):\n"
            "    # BUG: raises KeyError instead of falling back to default\n"
            "    return cfg[key]\n"
        ),
        "golden": (
            "def get_setting(cfg: dict, key: str, default=None):\n"
            "    # Fixed: use .get() with the provided default\n"
            "    return cfg.get(key, default)\n"
        ),
        "test": (
            "from broken.config import get_setting\n\n\n"
            "def test_get_setting_missing_key():\n"
            "    assert get_setting({}, 'timeout', 30) == 30\n"
            "    assert get_setting({'timeout': 5}, 'timeout', 30) == 5\n"
        ),
        "prompt": (
            "The file broken/config.py has get_setting using cfg[key] directly, "
            "which raises KeyError for missing keys instead of returning the "
            "default. Fix ONLY that line to use cfg.get(key, default). Return "
            "ONLY a unified diff (---/+++ @@) for broken/config.py. No markdown fences."
        ),
    },
    {
        "name": "mut_swapped_args",
        "module": "arith",
        "split": "train",
        "title": "Fix swapped operand order in subtraction",
        "broken": (
            "def subtract(a: float, b: float) -> float:\n"
            "    # BUG: operands are swapped\n"
            "    return b - a\n"
        ),
        "golden": (
            "def subtract(a: float, b: float) -> float:\n"
            "    # Fixed: correct operand order\n"
            "    return a - b\n"
        ),
        "test": (
            "from broken.arith import subtract\n\n\n"
            "def test_subtract():\n"
            "    assert subtract(10, 3) == 7\n"
            "    assert subtract(3, 10) == -7\n"
        ),
        "prompt": (
            "The file broken/arith.py has subtract(a, b) computing b - a instead "
            "of a - b. Fix ONLY the operand order. Return ONLY a unified diff "
            "(---/+++ @@) for broken/arith.py. No markdown fences."
        ),
    },
    {
        "name": "mut_is_vs_equals",
        "module": "checks",
        "split": "train",
        "title": "Fix identity check misused for value equality",
        "broken": (
            "def is_zero(x) -> bool:\n"
            "    # BUG: 'is' checks identity, not value equality\n"
            "    return x is 0\n"
        ),
        "golden": (
            "def is_zero(x) -> bool:\n"
            "    # Fixed: value comparison\n"
            "    return x == 0\n"
        ),
        "test": (
            "from broken.checks import is_zero\n\n\n"
            "def test_is_zero():\n"
            "    assert is_zero(0) is True\n"
            "    assert is_zero(0.0) is True\n"
            "    assert is_zero(1000 - 1000) is True\n"
        ),
        "prompt": (
            "The file broken/checks.py has is_zero using 'is 0' (identity check) "
            "instead of '== 0' (value check). Fix ONLY that comparison operator. "
            "Return ONLY a unified diff (---/+++ @@) for broken/checks.py. No markdown fences."
        ),
    },
    {
        "name": "mut_reversed_sort",
        "module": "ranking",
        "split": "train",
        "title": "Fix ascending sort used where descending was required",
        "broken": (
            "def top_n(values, n: int):\n"
            "    # BUG: ascending sort returns the smallest values, not the largest\n"
            "    return sorted(values)[:n]\n"
        ),
        "golden": (
            "def top_n(values, n: int):\n"
            "    # Fixed: sort descending to get the largest values\n"
            "    return sorted(values, reverse=True)[:n]\n"
        ),
        "test": (
            "from broken.ranking import top_n\n\n\n"
            "def test_top_n():\n"
            "    assert top_n([5, 1, 9, 3], 2) == [9, 5]\n"
            "    assert top_n([1, 2, 3], 1) == [3]\n"
        ),
        "prompt": (
            "The file broken/ranking.py has top_n returning the smallest values "
            "because it sorts ascending. Fix ONLY the sorted() call to sort "
            "descending (reverse=True). Return ONLY a unified diff (---/+++ @@) "
            "for broken/ranking.py. No markdown fences."
        ),
    },
    {
        "name": "mut_off_by_one_slice",
        "module": "splitter",
        "split": "train",
        "title": "Fix off-by-one slice bound dropping the middle element",
        "broken": (
            "def first_half(items: list) -> list:\n"
            "    # BUG: drops the middle element on odd-length input\n"
            "    return items[: len(items) // 2 - 1]\n"
        ),
        "golden": (
            "def first_half(items: list) -> list:\n"
            "    # Fixed: correct slice bound\n"
            "    return items[: len(items) // 2]\n"
        ),
        "test": (
            "from broken.splitter import first_half\n\n\n"
            "def test_first_half():\n"
            "    assert first_half([1, 2, 3, 4]) == [1, 2]\n"
            "    assert first_half([1, 2, 3, 4, 5]) == [1, 2]\n"
        ),
        "prompt": (
            "The file broken/splitter.py has first_half slicing with an extra "
            "'- 1' that drops an element. Fix ONLY the slice bound. Return ONLY "
            "a unified diff (---/+++ @@) for broken/splitter.py. No markdown fences."
        ),
    },
    {
        "name": "mut_wrong_exception_type",
        "module": "safe_math",
        "split": "train",
        "title": "Fix wrong exception type caught in safe division",
        "broken": (
            "def safe_div(a: float, b: float):\n"
            "    # BUG: catches the wrong exception type\n"
            "    try:\n"
            "        return a / b\n"
            "    except TypeError:\n"
            "        return None\n"
        ),
        "golden": (
            "def safe_div(a: float, b: float):\n"
            "    # Fixed: division by zero raises ZeroDivisionError\n"
            "    try:\n"
            "        return a / b\n"
            "    except ZeroDivisionError:\n"
            "        return None\n"
        ),
        "test": (
            "from broken.safe_math import safe_div\n\n\n"
            "def test_safe_div_zero():\n"
            "    assert safe_div(10, 2) == 5\n"
            "    assert safe_div(10, 0) is None\n"
        ),
        "prompt": (
            "The file broken/safe_math.py has safe_div catching TypeError instead "
            "of ZeroDivisionError, so dividing by zero still raises. Fix ONLY the "
            "except clause. Return ONLY a unified diff (---/+++ @@) for "
            "broken/safe_math.py. No markdown fences."
        ),
    },
    {
        "name": "mut_string_strip_missing",
        "module": "names",
        "split": "train",
        "title": "Fix missing strip() before normalizing a name",
        "broken": (
            "def clean_name(name: str) -> str:\n"
            "    # BUG: leaves leading/trailing whitespace in place\n"
            "    return name.lower()\n"
        ),
        "golden": (
            "def clean_name(name: str) -> str:\n"
            "    # Fixed: strip whitespace before lowercasing\n"
            "    return name.strip().lower()\n"
        ),
        "test": (
            "from broken.names import clean_name\n\n\n"
            "def test_clean_name():\n"
            "    assert clean_name('  Alice  ') == 'alice'\n"
            "    assert clean_name('BOB') == 'bob'\n"
        ),
        "prompt": (
            "The file broken/names.py has clean_name that lowercases but never "
            "strips surrounding whitespace. Add ONLY a .strip() call before "
            ".lower(). Return ONLY a unified diff (---/+++ @@) for broken/names.py. "
            "No markdown fences."
        ),
    },
    {
        "name": "mut_any_vs_all",
        "module": "quantifiers",
        "split": "train",
        "title": "Fix any()/all() confusion in positivity check",
        "broken": (
            "def all_positive(nums: list) -> bool:\n"
            "    # BUG: any() only requires ONE positive number\n"
            "    return any(n > 0 for n in nums)\n"
        ),
        "golden": (
            "def all_positive(nums: list) -> bool:\n"
            "    # Fixed: all() requires every number to be positive\n"
            "    return all(n > 0 for n in nums)\n"
        ),
        "test": (
            "from broken.quantifiers import all_positive\n\n\n"
            "def test_all_positive():\n"
            "    assert all_positive([1, 2, 3]) is True\n"
            "    assert all_positive([1, -2, 3]) is False\n"
        ),
        "prompt": (
            "The file broken/quantifiers.py has all_positive using any() where "
            "all() is required. Fix ONLY that function name. Return ONLY a "
            "unified diff (---/+++ @@) for broken/quantifiers.py. No markdown fences."
        ),
    },
    {
        "name": "mut_wrong_default_return",
        "module": "search",
        "split": "train",
        "title": "Fix wrong sentinel returned on failed search",
        "broken": (
            "def find_index(items: list, target) -> int:\n"
            "    i = -1\n"
            "    for i, v in enumerate(items):\n"
            "        if v == target:\n"
            "            return i\n"
            "    # BUG: returns the last loop index instead of -1 on miss\n"
            "    return i\n"
        ),
        "golden": (
            "def find_index(items: list, target) -> int:\n"
            "    for i, v in enumerate(items):\n"
            "        if v == target:\n"
            "            return i\n"
            "    # Fixed: -1 sentinel means not found\n"
            "    return -1\n"
        ),
        "test": (
            "from broken.search import find_index\n\n\n"
            "def test_find_index_not_found():\n"
            "    assert find_index([1, 2, 3], 2) == 1\n"
            "    assert find_index([1, 2, 3], 99) == -1\n"
        ),
        "prompt": (
            "The file broken/search.py has find_index returning the last loop "
            "index instead of -1 when the target is not found. Fix ONLY the "
            "fallback return value. Return ONLY a unified diff (---/+++ @@) for "
            "broken/search.py. No markdown fences."
        ),
    },
    {
        "name": "mut_negated_condition",
        "module": "empties",
        "split": "train",
        "title": "Fix inverted emptiness check",
        "broken": (
            "def is_empty(items: list) -> bool:\n"
            "    # BUG: condition is inverted\n"
            "    return len(items) != 0\n"
        ),
        "golden": (
            "def is_empty(items: list) -> bool:\n"
            "    # Fixed: empty means length is zero\n"
            "    return len(items) == 0\n"
        ),
        "test": (
            "from broken.empties import is_empty\n\n\n"
            "def test_is_empty():\n"
            "    assert is_empty([]) is True\n"
            "    assert is_empty([1]) is False\n"
        ),
        "prompt": (
            "The file broken/empties.py has is_empty using '!= 0' instead of "
            "'== 0', inverting the result. Fix ONLY that comparison operator. "
            "Return ONLY a unified diff (---/+++ @@) for broken/empties.py. "
            "No markdown fences."
        ),
    },
    {
        "name": "mut_wrong_comparison_bound",
        "module": "grader",
        "split": "train",
        "title": "Fix off-by-one grade threshold (strict vs inclusive bound)",
        "broken": (
            "def passed_threshold(score: float, cutoff: float) -> bool:\n"
            "    # BUG: '>' excludes a score exactly equal to the cutoff\n"
            "    return score > cutoff\n"
        ),
        "golden": (
            "def passed_threshold(score: float, cutoff: float) -> bool:\n"
            "    # Fixed: '>=' correctly treats the cutoff itself as passing\n"
            "    return score >= cutoff\n"
        ),
        "test": (
            "from broken.grader import passed_threshold\n\n\n"
            "def test_passed_threshold_inclusive():\n"
            "    assert passed_threshold(70, 70) is True\n"
            "    assert passed_threshold(69, 70) is False\n"
            "    assert passed_threshold(90, 70) is True\n"
        ),
        "prompt": (
            "The file broken/grader.py has passed_threshold using '>' where a "
            "score exactly equal to the cutoff must also pass. Fix ONLY that "
            "comparison operator to '>='. Return ONLY a unified diff (---/+++ @@) "
            "for broken/grader.py. No markdown fences."
        ),
    },
]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_pack(root: Path, tpl: Dict[str, Any]) -> Path:
    pack_dir = root / tpl["name"]
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
    (pack_dir / "broken").mkdir(parents=True, exist_ok=True)
    (pack_dir / "tests").mkdir(parents=True, exist_ok=True)

    (pack_dir / "broken" / "__init__.py").write_text(
        '"""Broken on purpose — sandbox CI pack (mutation)."""\n', encoding="utf-8"
    )
    (pack_dir / "tests" / "__init__.py").write_text("", encoding="utf-8")

    module = tpl["module"]
    broken_path = pack_dir / "broken" / f"{module}.py"
    broken_path.write_text(tpl["broken"], encoding="utf-8")

    test_path = pack_dir / "tests" / f"test_{module}.py"
    test_path.write_text(tpl["test"], encoding="utf-8")

    diff = difflib.unified_diff(
        tpl["broken"].splitlines(keepends=True),
        tpl["golden"].splitlines(keepends=True),
        fromfile=f"a/broken/{module}.py",
        tofile=f"b/broken/{module}.py",
    )
    patch_text = "".join(diff)
    (pack_dir / "golden.patch").write_text(patch_text, encoding="utf-8")

    task = {
        "task_key": f"ci_{tpl['name']}",
        "title": tpl["title"],
        "prompt": tpl["prompt"],
        "test_path": f"tests/test_{module}.py",
        "target_files": [f"broken/{module}.py"],
        "domain": "coding",
    }
    (pack_dir / "task.json").write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
    return pack_dir


def _run_pytest(workdir: Path, test_rel: str) -> bool:
    env = dict(**__import__("os").environ)
    env["PYTHONPATH"] = str(workdir) + __import__("os").pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", test_rel],
        cwd=str(workdir),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode == 0


def _self_verify(tpl: Dict[str, Any], pack_dir: Path) -> str:
    """Copy pack to temp dir; assert broken FAILS and golden-applied PASSES."""
    # Load the real runtime unified-diff applier so packs are guaranteed
    # compatible with the actual bakeoff/sandbox engine, not just difflib.
    ci_mod_path = REPO_ROOT / "backend" / "app" / "services" / "ln_sandbox_engineering_ci.py"
    spec = importlib.util.spec_from_file_location("ln_sandbox_engineering_ci", ci_mod_path)
    ci_mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(ci_mod)  # type: ignore[union-attr]

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        shutil.copytree(pack_dir, work, dirs_exist_ok=True)
        test_rel = json.loads((work / "task.json").read_text())["test_path"]

        if _run_pytest(work, test_rel):
            return "FAIL: broken tree unexpectedly passes pytest"

        diff_text = (work / "golden.patch").read_text(encoding="utf-8")
        ok_apply, notes = ci_mod.apply_unified_diff(work, diff_text)
        if not ok_apply:
            return f"FAIL: golden.patch did not apply cleanly ({notes})"

        if not _run_pytest(work, test_rel):
            return "FAIL: golden-patched tree still fails pytest"

    return "ok"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out-dir",
        default=str(REPO_ROOT / "backend" / "app" / "data" / "ln_sandbox_ci_packs"),
    )
    ap.add_argument(
        "--sql-out",
        default=str(REPO_ROOT / "backend" / "migrations" / "295_ln7_mutation_packs.sql"),
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    out_root = Path(args.out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    ok_names: List[str] = []
    heldout_names: List[str] = []
    sql_rows: List[str] = []
    failures: List[str] = []

    for tpl in TEMPLATES:
        pack_dir = _write_pack(out_root, tpl)
        verdict = _self_verify(tpl, pack_dir)
        if verdict != "ok":
            failures.append(f"{tpl['name']}: {verdict}")
            shutil.rmtree(pack_dir, ignore_errors=True)
            continue

        name = tpl["name"]
        split = tpl["split"]
        ok_names.append(name)
        if split == "heldout":
            heldout_names.append(name)

        task_id = f"pack:{name}"
        th = _sha256(f"{task_id}:v1")
        prompt_summary = tpl["title"].replace("'", "''")
        meta = json.dumps({"pack": name, "gold_files": [f"broken/{tpl['module']}.py"]}).replace("'", "''")
        sql_rows.append(
            "    (\n"
            f"        '{task_id}',\n"
            "        'mutation',\n"
            "        'easy',\n"
            f"        '{th}',\n"
            f"        '{split}',\n"
            f"        '{name}',\n"
            "        'FIRST-PARTY',\n"
            f"        '{prompt_summary}',\n"
            f"        '{meta}'::jsonb\n"
            "    )"
        )

    if failures:
        print("SELF-VERIFICATION FAILURES (pack not written):", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)

    print(f"generated + verified {len(ok_names)}/{len(TEMPLATES)} mutation packs")
    print(f"  heldout: {heldout_names}")
    print(f"  train:   {[n for n in ok_names if n not in heldout_names]}")

    if not args.dry_run and sql_rows:
        sql_path = Path(args.sql_out)
        sql_path.parent.mkdir(parents=True, exist_ok=True)
        sql_text = (
            "-- 295_ln7_mutation_packs.sql\n"
            "-- QUANTUM-CRYSTAL-ARCH — seed auto-generated mutation packs (G5 fix)\n"
            "-- Additive only. Grows ln7_tasks past 300 with source='mutation'.\n"
            "-- Generated by backend/scripts/ln7_generate_mutation_packs.py — every\n"
            "-- pack below was self-verified: broken tree fails pytest, golden.patch\n"
            "-- applied via the real runtime unified-diff applier makes it pass.\n\n"
            "INSERT INTO ln7_tasks (\n"
            "    task_id, source, difficulty, task_hash, split, pack_name,\n"
            "    spdx_license, prompt_summary, metadata_json\n"
            ")\nVALUES\n" + ",\n".join(sql_rows) + "\n"
            "ON CONFLICT (task_id) DO NOTHING;\n"
        )
        sql_path.write_text(sql_text, encoding="utf-8")
        print(f"wrote {sql_path}")

    # Emit the packs_index.json delta (names + heldout) for manual/automatic merge.
    index_delta = {"packs": ok_names, "heldout": heldout_names}
    print("packs_index.json delta:")
    print(json.dumps(index_delta, indent=2))

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
