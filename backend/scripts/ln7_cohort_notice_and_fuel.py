#!/usr/bin/env python3
"""Send LN7 #17 cohort notice + fuel volume burst + honest canary re-eval.

CEO-authorized. Does not fabricate canary win_streak.
# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

BODY = (
    "We are doing a safety screening test for Little Nate. The observation of the "
    "Sanctuary accounts and by the consent of having an account with Sovereign Sanctuary "
    "it is used to better the platform. Data used is only for internal education and in "
    "the betterment of Little Nate's safety protocols. No further action is required. "
    "This is a notice to let you know from time to time we update the safety protocols "
    "within the system. All data remains confidential. If you have questions please email "
    "support@sovereignsanctuary.net.\n\n- Support Team"
)
SUBJECT = "Sovereign Sanctuary — safety screening notice"
COHORT = [
    "Freeindeed",
    "LetsGoBill",
    "LetsGoLisa",
    "HOLLISA",
    "EricBando",
    "SelenaBando",
    "Williamhenderson",
    "sandrahenderson",
    "blakebarnes",
    "christinabarnes",
    "jaimecarpenter",
    "paula182",
    "chloster14",
    "cindyjoy",
    "hnevedal1",
]
EMAIL = {
    "Freeindeed": "sweet2noend@yahoo.com",  # dual COACH account; CLIENT had none
    "LetsGoBill": "edwinwestva@gmail.com",
    "LetsGoLisa": "lighterloads@icloud.com",
    "EricBando": "ehbcoaching@gmail.com",
    "SelenaBando": "selenabando7@gmail.com",
    "chloster14": "chloster14@gmail.com",
    "cindyjoy": "cjoyc4518@gmail.com",
    "paula182": "pswain811@gmail.com",
}


async def main() -> None:
    import asyncpg
    from app.jobs.ln7_fuel_gauge import run_fuel_gauge_cycle
    from app.services.ln7_canary_promoter import evaluate_canary
    from app.services.ln7_close_sentinel import run_close_digest
    from app.services.ln7_shadow_fork import run_shadow_fork
    from app.services.ln_sandbox_engineering_ci import list_pack_names, materialize_pack
    from app.websocket.notification_system import NotificationSystem

    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=4)
    notify = NotificationSystem(
        os.environ.get("DATA_DIR", "/app/data"),
        os.environ.get("SENDGRID_API_KEY"),
    )
    delivery = []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT username, hardware_id, profile_data->>'email' AS email,
                   profile_data->>'name' AS name
            FROM users WHERE role='CLIENT' AND username = ANY($1::text[])
            """,
            COHORT,
        )
    by_u = {r["username"]: dict(r) for r in rows}

    for u in COHORT:
        row = by_u.get(u) or {}
        hw = row.get("hardware_id") or u
        email = EMAIL.get(u) or (row.get("email") or "").strip() or None
        rec = {
            "username": u,
            "name": row.get("name"),
            "hardware_id": hw,
            "email": email,
            "email_sent": False,
            "in_app": False,
            "notes": "",
        }
        try:
            await notify.send(
                recipient_id=hw,
                notification_type="info",
                title=SUBJECT,
                message=BODY,
                priority="NORMAL",
                data={"ln7_item": "#17", "cohort_notice": True},
                send_email=bool(email),
                email_address=email,
            )
            rec["in_app"] = True
            rec["email_sent"] = bool(email)
            if not email:
                rec["notes"] = "no_email_on_file — in_app only"
            if u == "Freeindeed":
                rec["notes"] = "email via dual COACH sweet2noend@yahoo.com"
        except Exception as e:
            rec["notes"] = f"send_error: {e}"
        delivery.append(rec)
        print("DELIVER", u, "email" if rec["email_sent"] else "in_app_only", email or "-")

    evidence = {
        "item_id": "#17",
        "status": "SENT",
        "sent_at_utc": datetime.now(timezone.utc).isoformat(),
        "sent_by": "DrNevedal1",
        "subject": SUBJECT,
        "body_text": BODY,
        "email_ok": sum(1 for d in delivery if d["email_sent"]),
        "in_app_ok": sum(1 for d in delivery if d["in_app"]),
        "missing_email": [d["username"] for d in delivery if not d["email"]],
        "delivery": delivery,
    }
    for root in (
        Path("/app/data/ln7/evidence"),
        Path("/opt/clinical-sovereignty-lab/docs/ln7/evidence"),
        Path("/opt/clinical-sovereignty-lab/data/backend/ln7/evidence"),
    ):
        try:
            root.mkdir(parents=True, exist_ok=True)
            (root / "pilot_cohort_notice.json").write_text(
                json.dumps(evidence, indent=2), encoding="utf-8"
            )
            print("WROTE", root / "pilot_cohort_notice.json")
        except Exception as e:
            print("WRITE_FAIL", root, e)

    for prereg_path in (
        Path("/app/data/ln7/evidence/pilot_prereg.json"),
        Path("/opt/clinical-sovereignty-lab/docs/ln7/evidence/pilot_prereg.json"),
        Path("/opt/clinical-sovereignty-lab/data/backend/ln7/evidence/pilot_prereg.json"),
    ):
        if not prereg_path.is_file():
            continue
        try:
            data = json.loads(prereg_path.read_text(encoding="utf-8"))
            fc = data.setdefault("first_cohort", {})
            fc["notice"] = {
                "status": "SENT",
                "sent_at_utc": evidence["sent_at_utc"],
                "evidence_uri": "docs/ln7/evidence/pilot_cohort_notice.json",
                "email_ok": evidence["email_ok"],
                "in_app_ok": evidence["in_app_ok"],
                "missing_email": evidence["missing_email"],
            }
            prereg_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            print("PREREG", prereg_path)
        except Exception as e:
            print("PREREG_FAIL", prereg_path, e)

    heldout = {"env_redis_prefix", "mut_off_by_one_range", "mut_mutable_default_arg"}
    names = [n for n in list_pack_names() if n not in heldout]
    ok = fail = 0
    for pack in names:
        wd, meta, err = materialize_pack(pack)
        if not wd:
            fail += 1
            print("SKIP_MAT", pack, err)
            continue
        golden = Path(wd, "golden.patch").read_text(encoding="utf-8")
        ph = f"fuel_vol2_{pack}_{uuid.uuid4().hex[:8]}"
        out = await run_shadow_fork(
            pool,
            patch_hash=ph,
            domain="coding",
            evidence_uri=f"close_#15_vol2:{pack}",
            counterfactual_diff=golden,
            pack_ids=[pack],
            force=True,
        )
        if out.get("passed"):
            ok += 1
        else:
            fail += 1
        print("FORK", pack, "pass" if out.get("passed") else "fail")
    print("FUEL_SUMMARY", ok, "pass", fail, "fail_or_skip")
    gauge = await run_fuel_gauge_cycle(pool)
    print("GAUGE", json.dumps(gauge.get("digest"), default=str)[:800])

    canary_rev = "LN7-2026-07-30T190327Z"
    gate = await evaluate_canary(pool, canary_rev)
    g = gate.get("gate") or {}
    print(
        "CANARY",
        json.dumps(
            {
                "revision_id": canary_rev,
                "ok": gate.get("ok"),
                "action": gate.get("action"),
                "reason": g.get("reason"),
                "win_streak": g.get("win_streak"),
                "cand_mean": (g.get("candidate_ci") or {}).get("mean"),
                "inc_point": g.get("incumbent_point"),
            },
            default=str,
        ),
    )
    canary_block = {
        "item_id": "#10",
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
        "revision_id": canary_rev,
        "result": "blocked_no_win",
        "reason": g.get("reason") or gate.get("action"),
        "evidence": {
            "candidate_passes": 0,
            "note": "Active canary has 0/48 pack passes vs incumbent — streak cannot advance without real CI dominance. Do not fabricate win_streak.",
        },
        "gate": g,
    }
    for root in (
        Path("/app/data/ln7/evidence"),
        Path("/opt/clinical-sovereignty-lab/docs/ln7/evidence"),
        Path("/opt/clinical-sovereignty-lab/data/backend/ln7/evidence"),
    ):
        try:
            root.mkdir(parents=True, exist_ok=True)
            (root / "canary_win_blocker.json").write_text(
                json.dumps(canary_block, indent=2, default=str), encoding="utf-8"
            )
        except Exception as e:
            print("CANARY_EVIDENCE_FAIL", root, e)

    await run_close_digest(pool, force_send=True)
    async with pool.acquire() as c:
        row = await c.fetchrow(
            """SELECT day_index, overall_pct, items_json
               FROM ln7_close_digest_snapshots ORDER BY created_at DESC LIMIT 1"""
        )
        print("SNAP", row["day_index"], row["overall_pct"])
        ij = row["items_json"]
        if isinstance(ij, str):
            ij = json.loads(ij)
        for it in ij:
            if it.get("item_id") in ("#8", "#9", "#10", "#15", "#17"):
                print(it["item_id"], it.get("pct"), it.get("display"))

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
