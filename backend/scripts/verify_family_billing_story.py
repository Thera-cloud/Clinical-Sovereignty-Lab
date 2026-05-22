#!/usr/bin/env python3
"""Family billing full-story verifier — prints pass/fail checklist.

Run from repo root:
  cd backend && python3 scripts/verify_family_billing_story.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock
from contextlib import asynccontextmanager

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _ok(label: str, passed: bool) -> bool:
    mark = "✅ PASS" if passed else "❌ FAIL"
    print(f"{mark}  {label}")
    return passed


def _static_checks() -> list[bool]:
    """Source-level wiring checks (no live Stripe/API)."""
    results: list[bool] = []
    root = Path(__file__).resolve().parents[2]
    bridge = (root / "backend/app/websocket/bridge_server.py").read_text(encoding="utf-8")
    flutter = (root / "mobile/lib/main.dart").read_text(encoding="utf-8")
    checkout = (root / "backend/app/routers/registration_checkout.py").read_text(encoding="utf-8")

    print("\n--- Invites ---")
    results.append(_ok("Flutter passes familyRole to SignUpWizard", "familyRole: _role" in flutter))
    results.append(_ok("Flutter sends family_role to /dependent-price", "qp['family_role']" in flutter))
    results.append(_ok("Flutter sends family_role to checkout/prepare", "body['family_role']" in flutter))
    results.append(_ok("REST /dependent-price accepts family_role", "family_role" in checkout and "compute_family_member_billing" in checkout))
    results.append(_ok("Bridge accept_family_invite blocks 2nd spouse", "Only one Spouse is allowed per family" in bridge and "accept_family_invite" in bridge))

    print("\n--- Sign ups (WebSocket + REST paths) ---")
    results.append(_ok("Bridge register_new_user billing gate", "QUANTUM-CRYSTAL-ARCH: block unpaid 2nd+ dependents" in bridge))
    results.append(_ok("Bridge create_dependent_account paid slot gate", 'return False, "DEPENDENT_REQUIRES_PAYMENT"' in bridge))
    results.append(_ok("Flutter blocks free WS register when paid tier", "_hasFamilyJoinContext && _isPaidTier" in flutter))
    results.append(_ok("REST finalize_dependent_signup role-aware", "family_role" in (root / "backend/app/services/registration_finalize.py").read_text(encoding="utf-8")))

    return results


def main() -> int:
    print("=== Full story family billing verification ===\n")
    print("--- Billing rules (compute_family_member_billing) ---")
    from app.services.registration_finalize import (
        compute_family_member_billing,
        normalize_family_member_role,
        finalize_dependent_signup,
        _family_tier_price_cents,
    )

    results: list[bool] = []

    results.append(_ok("1st dependent free (0 existing)", compute_family_member_billing(
        family_role="DEPENDENT", existing_dependent_count=0
    )["free"]))

    results.append(_ok("2nd dependent $75 (1 existing)", compute_family_member_billing(
        family_role="DEPENDENT", existing_dependent_count=1
    )["monthly_cost_cents"] == 7500))

    results.append(_ok("3rd dependent $60 (2 existing)", compute_family_member_billing(
        family_role="DEPENDENT", existing_dependent_count=2
    )["monthly_cost_cents"] == 6000))

    results.append(_ok("4th dependent $45 (3 existing)", compute_family_member_billing(
        family_role="DEPENDENT", existing_dependent_count=3
    )["monthly_cost_cents"] == 4500))

    results.append(_ok("5th+ dependent $30 (4+ existing)", _family_tier_price_cents(4) == 3000))

    results.append(_ok("Spouse free with 0 dependents", compute_family_member_billing(
        family_role="SPOUSE", existing_dependent_count=0
    )["free"]))

    results.append(_ok("Spouse free with 3 dependents", compute_family_member_billing(
        family_role="SPOUSE", existing_dependent_count=3
    )["free"]))

    results.append(_ok("Spouse + 1st dependent both free slots", (
        compute_family_member_billing(family_role="SPOUSE", existing_dependent_count=1)["free"]
        and compute_family_member_billing(family_role="DEPENDENT", existing_dependent_count=0)["free"]
    )))

    results.append(_ok("PARTNER normalizes to SPOUSE", normalize_family_member_role("PARTNER") == "SPOUSE"))

    async def _run_finalize_cases():
        parent_row = {
            "id": "parent-uuid",
            "family_id": "fam-uuid",
            "tier": "TOP_TIER",
            "subscription_status": "ACTIVE",
            "name": "HoHUser",
            "stripe_customer_id": "cus_test",
            "stripe_subscription_id": "sub_test",
        }

        async def _fetchrow(sql, *args):
            if "FROM users" in sql and "LOWER(username)" in sql and "role = 'CLIENT'" in sql:
                return parent_row
            return None

        async def _fetchval(sql, *args):
            if "SELECT 1 FROM users" in sql:
                return None
            if "head_of_household_id" in sql:
                return "parent-uuid"
            if "spouse" in sql.lower() and "COUNT" in sql:
                return 0
            if "tier = 'DEPENDENT'" in sql or "family_role" in sql.lower():
                if "spouse" in sql.lower():
                    return 0
                return 1
            if "INSERT INTO users" in sql:
                return "new-id"
            return None

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=_fetchrow)
        conn.fetchval = AsyncMock(side_effect=_fetchval)
        conn.execute = AsyncMock()

        @asynccontextmanager
        async def _acquire():
            yield conn

        pool = AsyncMock()
        pool.acquire = _acquire

        ok_spouse, reason_spouse, info_spouse = await finalize_dependent_signup(
            pool,
            username="sp1",
            password_hash="x",
            email="sp1@t.com",
            profile_fields={"name": "Sp", "dob": "1990-01-01"},
            parent_username="HoHUser",
            family_role="SPOUSE",
        )
        results.append(_ok("REST finalize: spouse free when deps exist", ok_spouse and info_spouse.get("monthly_cost_cents") == 0))

        conn.fetchval = AsyncMock(side_effect=_fetchval)
        ok_paid, reason_paid, info_paid = await finalize_dependent_signup(
            pool,
            username="kid2",
            password_hash="x",
            email="k2@t.com",
            profile_fields={"name": "Kid2", "dob": "2015-01-01"},
            parent_username="HoHUser",
            family_role="DEPENDENT",
        )
        results.append(_ok("REST finalize: 2nd dependent → Stripe ($75)", (
            not ok_paid and reason_paid == "DEPENDENT_REQUIRES_PAYMENT" and info_paid.get("monthly_cost_cents") == 7500
        )))

        async def _fetchval_spouse_exists(sql, *args):
            if "spouse" in sql.lower() and "COUNT" in sql:
                return 1
            if "SELECT 1 FROM users" in sql:
                return None
            if "head_of_household_id" in sql:
                return "parent-uuid"
            return 0

        conn.fetchval = AsyncMock(side_effect=_fetchval_spouse_exists)
        ok_dup, reason_dup, _ = await finalize_dependent_signup(
            pool,
            username="sp2",
            password_hash="x",
            email="sp2@t.com",
            profile_fields={"name": "Sp2", "dob": "1990-01-01"},
            parent_username="HoHUser",
            family_role="SPOUSE",
        )
        results.append(_ok("One spouse only (2nd rejected)", not ok_dup and reason_dup == "SPOUSE_ALREADY_LINKED"))

    asyncio.run(_run_finalize_cases())

    print("\n--- Stripe billing ---")
    results.append(_ok("Stripe billing ladder keys (TIER_1..4)", all(
        compute_family_member_billing(family_role="DEPENDENT", existing_dependent_count=n).get("family_tier_price_key")
        == f"STRIPE_PRICE_FAMILY_TIER_{min(n, 4)}"
        for n in (1, 2, 3, 4)
    )))

    import subprocess
    print("\n--- Automated tests (pytest) ---")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_family_checkout.py", "-q"],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
    )
    pytest_ok = proc.returncode == 0 and "passed" in proc.stdout
    results.append(_ok("test_family_checkout.py (26 tests)", pytest_ok))
    if not pytest_ok and proc.stdout:
        print(proc.stdout[-500:])

    results.extend(_static_checks())

    passed = sum(results)
    total = len(results)
    print(f"\n{'=' * 40}\nFull story: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
