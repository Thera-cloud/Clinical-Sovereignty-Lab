#!/usr/bin/env python3
"""Materialize additional LN7 sandbox CI train packs (broken + test + golden).

Heldout pack env_redis_prefix is never overwritten. Run from repo root:

  PYTHONPATH=backend python backend/scripts/ln7_seed_train_packs.py

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKS = ROOT / "backend" / "app" / "data" / "ln_sandbox_ci_packs"

# name -> (broken_relpath, broken_src, test_src, golden_unified_body_without_headers, prompt, title)
# golden uses --- a/ + +++ b/ for broken/<file>
SPECS = [
    (
        "load_dotenv_override",
        "broken/config.py",
        '"""Broken — override=True clobbers Docker env."""\n\n'
        "def load_settings_call() -> str:\n"
        '    # BUG: override=True wipes REDIS_HOST from compose\n'
        '    return "load_dotenv(override=True)"\n\n'
        "def looks_fixed(s: str) -> bool:\n"
        '    return "override=True" not in s.replace(" ", "") and "load_dotenv" in s\n',
        "from broken.config import load_settings_call, looks_fixed\n\n\n"
        "def test_no_override_true():\n"
        "    assert looks_fixed(load_settings_call())\n",
        [
            "@@ -2,7 +2,7 @@",
            "",
            " def load_settings_call() -> str:",
            "-    # BUG: override=True wipes REDIS_HOST from compose",
            "+    # Fixed: never clobber Docker-injected env",
            '-    return "load_dotenv(override=True)"',
            '+    return "load_dotenv()"',
            "",
        ],
        "broken/config.py calls load_dotenv(override=True). Change ONLY the return string to "
        "load_dotenv() (no override). Update the BUG comment. Return ONLY a unified diff.",
        "Forbid load_dotenv(override=True)",
    ),
    (
        "users_no_user_id_column",
        "broken/lookup.py",
        '"""Broken — users.user_id does not exist."""\n\n'
        "def user_lookup_sql() -> str:\n"
        '    # BUG: users has username/id, not user_id\n'
        '    return "SELECT * FROM users WHERE user_id = $1"\n\n'
        "def looks_fixed(s: str) -> bool:\n"
        '    t = s.lower()\n'
        '    return "username" in t and "user_id" not in t\n',
        "from broken.lookup import user_lookup_sql, looks_fixed\n\n\n"
        "def test_uses_username():\n"
        "    assert looks_fixed(user_lookup_sql())\n",
        [
            "@@ -2,7 +2,7 @@",
            "",
            " def user_lookup_sql() -> str:",
            "-    # BUG: users has username/id, not user_id",
            "+    # Fixed: lookup by username",
            '-    return "SELECT * FROM users WHERE user_id = $1"',
            '+    return "SELECT * FROM users WHERE username = $1"',
            "",
        ],
        "broken/lookup.py queries users.user_id which does not exist. Change WHERE to username = $1. "
        "Return ONLY a unified diff for broken/lookup.py.",
        "Fix users.user_id → username",
    ),
    (
        "skyeye_activity_columns",
        "broken/activity.py",
        '"""Broken — wrong skyeye_activity column names."""\n\n'
        "def insert_activity_sql() -> str:\n"
        '    # BUG: columns are type, content, created_at\n'
        '    return "INSERT INTO skyeye_activity (action, details, timestamp) VALUES ($1,$2,$3)"\n\n'
        "def looks_fixed(s: str) -> bool:\n"
        '    t = s.lower()\n'
        '    return "type" in t and "content" in t and "created_at" in t and "action" not in t\n',
        "from broken.activity import insert_activity_sql, looks_fixed\n\n\n"
        "def test_column_names():\n"
        "    assert looks_fixed(insert_activity_sql())\n",
        [
            "@@ -2,7 +2,7 @@",
            "",
            " def insert_activity_sql() -> str:",
            "-    # BUG: columns are type, content, created_at",
            "+    # Fixed: canonical skyeye_activity columns",
            '-    return "INSERT INTO skyeye_activity (action, details, timestamp) VALUES ($1,$2,$3)"',
            '+    return "INSERT INTO skyeye_activity (type, content, created_at) VALUES ($1,$2,$3)"',
            "",
        ],
        "broken/activity.py uses action/details/timestamp. Change to type, content, created_at. "
        "Return ONLY a unified diff.",
        "Fix skyeye_activity column names",
    ),
    (
        "require_coach_gate",
        "broken/deps.py",
        '"""Broken — coach endpoint gated admin-only."""\n\n'
        "def auth_dependency() -> str:\n"
        '    # BUG: coaches get 403 with require_admin\n'
        '    return "Depends(require_admin)"\n\n'
        "def looks_fixed(s: str) -> bool:\n"
        '    return "require_coach" in s and "require_admin" not in s\n',
        "from broken.deps import auth_dependency, looks_fixed\n\n\n"
        "def test_coach_dep():\n"
        "    assert looks_fixed(auth_dependency())\n",
        [
            "@@ -2,7 +2,7 @@",
            "",
            " def auth_dependency() -> str:",
            "-    # BUG: coaches get 403 with require_admin",
            "+    # Fixed: coach + admin",
            '-    return "Depends(require_admin)"',
            '+    return "Depends(require_coach)"',
            "",
        ],
        "Coach portal dependency uses require_admin. Change to require_coach. Return ONLY a unified diff.",
        "Use require_coach for coach routes",
    ),
    (
        "ws_ping_timeout",
        "broken/bridge.py",
        '"""Broken — WebSocket ping_timeout too short under load."""\n\n'
        "def serve_kwargs() -> dict:\n"
        "    # BUG: 10s kills connections mid-inference\n"
        '    return {"ping_interval": 20, "ping_timeout": 10, "close_timeout": 30}\n\n'
        "def looks_fixed(d: dict) -> bool:\n"
        '    return int(d.get("ping_timeout") or 0) >= 60\n',
        "from broken.bridge import serve_kwargs, looks_fixed\n\n\n"
        "def test_ping_timeout():\n"
        "    assert looks_fixed(serve_kwargs())\n",
        [
            "@@ -2,7 +2,7 @@",
            "",
            " def serve_kwargs() -> dict:",
            "-    # BUG: 10s kills connections mid-inference",
            "+    # Fixed: load-test baseline ping_timeout=60",
            '-    return {"ping_interval": 20, "ping_timeout": 10, "close_timeout": 30}',
            '+    return {"ping_interval": 20, "ping_timeout": 60, "close_timeout": 30}',
            "",
        ],
        "broken/bridge.py sets ping_timeout=10. Raise to 60. Return ONLY a unified diff.",
        "Raise WebSocket ping_timeout to 60",
    ),
    (
        "empty_dict_trusted",
        "broken/api.py",
        '"""Broken — empty dict fails auditor L2."""\n\n'
        "def list_response() -> object:\n"
        "    # BUG: {} is WARNING for auditors; use []\n"
        "    return {}\n\n"
        "def looks_fixed(v) -> bool:\n"
        "    return isinstance(v, list)\n",
        "from broken.api import list_response, looks_fixed\n\n\n"
        "def test_empty_list():\n"
        "    assert looks_fixed(list_response())\n",
        [
            "@@ -2,7 +2,7 @@",
            "",
            " def list_response() -> object:",
            "-    # BUG: {} is WARNING for auditors; use []",
            "+    # Fixed: empty collection as list",
            "-    return {}",
            "+    return []",
            "",
        ],
        "broken/api.py returns {}. Return [] for empty collections. Return ONLY a unified diff.",
        "Return [] not {} for empty collections",
    ),
    (
        "expected_role_login",
        "broken/login.py",
        '"""Broken — login_request missing expected_role."""\n\n'
        "def login_payload(username: str, password: str, role: str) -> dict:\n"
        "    # BUG: dual CLIENT/COACH accounts need expected_role\n"
        '    return {"type": "login_request", "username": username, "password": password}\n\n'
        "def looks_fixed(d: dict) -> bool:\n"
        '    return d.get("expected_role") in ("CLIENT", "COACH", "ADMIN")\n',
        "from broken.login import login_payload, looks_fixed\n\n\n"
        "def test_expected_role():\n"
        '    assert looks_fixed(login_payload("u", "p", "COACH"))\n',
        [
            "@@ -2,8 +2,10 @@",
            "",
            " def login_payload(username: str, password: str, role: str) -> dict:",
            "-    # BUG: dual CLIENT/COACH accounts need expected_role",
            "+    # Fixed: always pass expected_role",
            '-    return {"type": "login_request", "username": username, "password": password}',
            "+    return {",
            '+        "type": "login_request",',
            '+        "username": username,',
            '+        "password": password,',
            '+        "expected_role": role,',
            "+    }",
            "",
        ],
        "broken/login.py omits expected_role. Include expected_role=role in the payload dict. "
        "Return ONLY a unified diff.",
        "Pass expected_role on login_request",
    ),
    (
        "jsonb_set_token",
        "broken/billing.py",
        '"""Broken — full profile_data replace clobbers token_balance."""\n\n'
        "def reset_usage_sql() -> str:\n"
        "    # BUG: must jsonb_set not replace whole profile_data\n"
        '    return "UPDATE users SET profile_data = $1"\n\n'
        "def looks_fixed(s: str) -> bool:\n"
        '    return "jsonb_set" in s.lower()\n',
        "from broken.billing import reset_usage_sql, looks_fixed\n\n\n"
        "def test_jsonb_set():\n"
        "    assert looks_fixed(reset_usage_sql())\n",
        [
            "@@ -2,7 +2,7 @@",
            "",
            " def reset_usage_sql() -> str:",
            "-    # BUG: must jsonb_set not replace whole profile_data",
            "+    # Fixed: patch one key",
            '-    return "UPDATE users SET profile_data = $1"',
            '+    return "UPDATE users SET profile_data = jsonb_set(profile_data, \'{token_usage_today}\', \'0\')"',
            "",
        ],
        "broken/billing.py replaces profile_data entirely. Use jsonb_set for token_usage_today. "
        "Return ONLY a unified diff.",
        "Use jsonb_set for token usage reset",
    ),
    (
        "redis_environment_prefix",
        "broken/auth_keys.py",
        '"""Broken — ENVIRONMENT mismatch breaks REST auth."""\n\n'
        "def token_key(env: str, token: str) -> str:\n"
        "    # BUG: hardcodes development while bridge uses production\n"
        '    return f"nate:development:auth:{token}"\n\n'
        "def looks_fixed(key: str) -> bool:\n"
        '    return key.startswith("nate:") and ":development:" not in key\n',
        "from broken.auth_keys import token_key, looks_fixed\n\n\n"
        "def test_env_prefix():\n"
        '    assert looks_fixed(token_key("production", "abc"))\n',
        [
            "@@ -2,7 +2,7 @@",
            "",
            " def token_key(env: str, token: str) -> str:",
            "-    # BUG: hardcodes development while bridge uses production",
            "+    # Fixed: use ENVIRONMENT argument",
            '-    return f"nate:development:auth:{token}"',
            '+    return f"nate:{env}:auth:{token}"',
            "",
        ],
        "broken/auth_keys.py hardcodes nate:development:auth. Use env parameter. Return ONLY a unified diff.",
        "Redis auth key must use ENVIRONMENT",
    ),
    (
        "auditor_status_codes",
        "broken/auditor.py",
        '"""Broken — auditor TRUSTED set too strict."""\n\n'
        "def is_trusted(code: int) -> bool:\n"
        "    # BUG: must accept 200,400,404,422\n"
        "    return code in (200, 422)\n\n"
        "def looks_fixed(fn) -> bool:\n"
        "    return all(fn(c) for c in (200, 400, 404, 422))\n",
        "from broken.auditor import is_trusted, looks_fixed\n\n\n"
        "def test_trusted_codes():\n"
        "    assert looks_fixed(is_trusted)\n",
        [
            "@@ -2,7 +2,7 @@",
            "",
            " def is_trusted(code: int) -> bool:",
            "-    # BUG: must accept 200,400,404,422",
            "+    # Fixed: canonical TRUSTED set",
            "-    return code in (200, 422)",
            "+    return code in (200, 400, 404, 422)",
            "",
        ],
        "broken/auditor.py only trusts 200/422. Accept 200,400,404,422. Return ONLY a unified diff.",
        "Auditor TRUSTED status codes",
    ),
    (
        "vectorize_outside_db",
        "broken/crystallizer.py",
        '"""Broken — network call holds DB connection."""\n\n'
        "FLOW = [\"acquire\", \"insert\", \"vectorize\", \"release\"]\n\n"
        "def vectorize_after_release(flow=None) -> bool:\n"
        "    # BUG: vectorize must be after release\n"
        "    flow = flow if flow is not None else FLOW\n"
        '    return flow.index("vectorize") > flow.index("release")\n',
        "from broken.crystallizer import FLOW, vectorize_after_release\n\n\n"
        "def test_order():\n"
        '    fixed = ["acquire", "insert", "release", "vectorize"]\n'
        "    assert vectorize_after_release(fixed)\n"
        "    # also ensure module FLOW itself is fixed for static checks\n"
        '    assert FLOW.index("vectorize") > FLOW.index("release")\n',
        [
            "@@ -1,6 +1,6 @@",
            ' """Broken — network call holds DB connection."""',
            "",
            '-FLOW = ["acquire", "insert", "vectorize", "release"]',
            '+FLOW = ["acquire", "insert", "release", "vectorize"]',
            "",
        ],
        "broken/crystallizer.py runs vectorize before release. Reorder FLOW so vectorize is after release. "
        "Return ONLY a unified diff.",
        "Vectorize outside DB acquire block",
    ),
    (
        "no_iframe_embed",
        "broken/dashboard.py",
        '"""Broken — Hive Defense must not use iframe."""\n\n'
        "def embed_hive() -> str:\n"
        "    # BUG: iframe blocked by X-Frame-Options\n"
        '    return \'<iframe src="hive_defense.html"></iframe>\'\n\n'
        "def looks_fixed(html: str) -> bool:\n"
        '    return "iframe" not in html and "tab-hive" in html\n',
        "from broken.dashboard import embed_hive, looks_fixed\n\n\n"
        "def test_native_tab():\n"
        "    assert looks_fixed(embed_hive())\n",
        [
            "@@ -2,7 +2,7 @@",
            "",
            " def embed_hive() -> str:",
            "-    # BUG: iframe blocked by X-Frame-Options",
            "+    # Fixed: native tab section",
            '-    return \'<iframe src="hive_defense.html"></iframe>\'',
            '+    return \'<section class="tab-content" id="tab-hive"></section>\'',
            "",
        ],
        "broken/dashboard.py embeds via iframe. Return a native section#tab-hive instead. "
        "Return ONLY a unified diff.",
        "No iframe embeds for Hive Defense",
    ),
    (
        "coach_three_fields",
        "broken/register.py",
        '"""Broken — registration missing coach_id."""\n\n'
        "def new_client_profile(coach_hw: str, coach_user: str) -> dict:\n"
        "    # BUG: need coach_id + assigned_coach_id + assigned_coach\n"
        '    return {"assigned_coach": coach_user}\n\n'
        "def looks_fixed(d: dict) -> bool:\n"
        '    return all(k in d for k in ("coach_id", "assigned_coach_id", "assigned_coach"))\n',
        "from broken.register import new_client_profile, looks_fixed\n\n\n"
        "def test_three_fields():\n"
        '    assert looks_fixed(new_client_profile("COACH_X", "CoachX"))\n',
        [
            "@@ -2,8 +2,12 @@",
            "",
            " def new_client_profile(coach_hw: str, coach_user: str) -> dict:",
            "-    # BUG: need coach_id + assigned_coach_id + assigned_coach",
            "+    # Fixed: all three assignment fields",
            '-    return {"assigned_coach": coach_user}',
            "+    return {",
            '+        "coach_id": coach_hw,',
            '+        "assigned_coach_id": coach_hw,',
            '+        "assigned_coach": coach_user,',
            "+    }",
            "",
        ],
        "broken/register.py only sets assigned_coach. Set coach_id, assigned_coach_id, and assigned_coach. "
        "Return ONLY a unified diff.",
        "Set all three coach assignment fields",
    ),
    (
        "middleware_not_in_lifespan",
        "broken/main.py",
        '"""Broken — middleware registered inside lifespan."""\n\n'
        "PHASE = \"lifespan\"\n\n"
        "def add_middleware_phase() -> str:\n"
        "    # BUG: Starlette forbids middleware after start\n"
        "    return PHASE\n\n"
        "def looks_fixed(phase: str) -> bool:\n"
        '    return phase == "module"\n',
        "from broken.main import add_middleware_phase, looks_fixed\n\n\n"
        "def test_module_level():\n"
        "    assert looks_fixed(add_middleware_phase())\n",
        [
            "@@ -1,8 +1,8 @@",
            ' """Broken — middleware registered inside lifespan."""',
            "",
            '-PHASE = "lifespan"',
            '+PHASE = "module"',
            "",
        ],
        "broken/main.py sets PHASE=lifespan for middleware. Change PHASE to module. Return ONLY a unified diff.",
        "Register middleware at module level",
    ),
    (
        "flutter_nocache_sw",
        "broken/nginx.conf",
        "# Broken — service worker cached by Safari\n"
        "location = /flutter_service_worker.js {\n"
        "  # BUG: missing no-cache\n"
        "  add_header Cache-Control \"max-age=14400\";\n"
        "}\n",
        "from pathlib import Path\n\n"
        "def test_nocache():\n"
        "    text = Path('broken/nginx.conf').read_text()\n"
        '    assert "no-cache" in text\n'
        '    assert "max-age=14400" not in text\n',
        [
            "@@ -1,6 +1,6 @@",
            " # Broken — service worker cached by Safari",
            " location = /flutter_service_worker.js {",
            "-  # BUG: missing no-cache",
            "+  # Fixed: Safari must not pin stale SW",
            '-  add_header Cache-Control "max-age=14400";',
            '+  add_header Cache-Control "no-cache, no-store, must-revalidate";',
            " }",
            "",
        ],
        "broken/nginx.conf caches flutter_service_worker.js for 4h. Set Cache-Control to "
        "no-cache, no-store, must-revalidate. Return ONLY a unified diff.",
        "No-cache flutter_service_worker.js",
    ),
]


def _write_pack(name: str, rel: str, broken: str, test: str, hunk_lines: list, prompt: str, title: str) -> None:
    root = PACKS / name
    bpath = root / rel
    bpath.parent.mkdir(parents=True, exist_ok=True)
    (root / "broken").mkdir(exist_ok=True)
    (root / "tests").mkdir(exist_ok=True)
    (root / "broken" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests" / "__init__.py").write_text("", encoding="utf-8")
    bpath.write_text(broken, encoding="utf-8")
    tname = "test_" + Path(rel).stem + ".py"
    (root / "tests" / tname).write_text(test, encoding="utf-8")
    test_path = f"tests/{tname}"

    golden = (
        f"--- a/{rel}\t2026-07-28 00:00:00\n"
        f"+++ b/{rel}\t2026-07-28 00:00:00\n"
        + "\n".join(hunk_lines)
    )
    if not golden.endswith("\n"):
        golden += "\n"
    (root / "golden.patch").write_text(golden, encoding="utf-8")
    task = {
        "task_key": f"ci_{name}",
        "title": title,
        "prompt": prompt + " No markdown fences.",
        "test_path": test_path,
        "target_files": [rel],
        "domain": "coding",
        "split": "train",
    }
    (root / "task.json").write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    names = []
    for name, rel, broken, test, hunk, prompt, title in SPECS:
        _write_pack(name, rel, broken, test, hunk, prompt, title)
        names.append(name)

    # Preserve heldout + existing order, append new
    base = ["asyncpg_cast", "catch_all_routes", "env_redis_prefix"]
    packs = base + [n for n in names if n not in base]
    idx = {
        "version": 2,
        "description": "Disposable micro-repos for LN Sandbox Engineering CI. Never mutates GREEN prod tree.",
        "heldout": ["env_redis_prefix"],
        "packs": packs,
    }
    (PACKS / "packs_index.json").write_text(json.dumps(idx, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "seeded": names, "total_packs": len(packs)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
