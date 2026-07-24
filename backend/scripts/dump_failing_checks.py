"""One-off: run selected auditors in-container and print non-TRUSTED checks. # QUANTUM-CRYSTAL-ARCH"""
import asyncio
import json
import os
import sys

sys.path.insert(0, "/app")


async def main():
    import asyncpg
    dsn = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg", "postgresql")
    pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=2)

    from app.services.coach_dojo_auditor import CoachDojoAuditor
    from app.services.command_tab_auditor import SovereignCommandAuditor as CommandTabAuditor
    from app.services.token_lab_auditor import TokenLabAuditor
    from app.services.wisdom_pipeline_auditor import WisdomPipelineAuditor

    auditors = {
        "coach_dojo": CoachDojoAuditor,
        "command_tab": CommandTabAuditor,
        "token_lab": TokenLabAuditor,
        "wisdom_pipeline": WisdomPipelineAuditor,
    }
    for name, cls in auditors.items():
        try:
            try:
                a = cls(db_pool=pool)
            except TypeError:
                a = cls(pool)
            results = await a._audit_all_tabs() if hasattr(a, "_audit_all_tabs") else await a._audit_all_checks()
            print(f"== {name}")
            def walk(o):
                if isinstance(o, dict):
                    st = str(o.get("status", "")).upper()
                    if st and st not in ("TRUSTED", "PASS", "OK"):
                        print("  ", json.dumps(o, default=str)[:260])
                    for v in o.values():
                        walk(v)
                elif isinstance(o, list):
                    for v in o:
                        walk(v)
            walk(results)
        except Exception as e:
            print(f"== {name} ERROR: {e}")
    await pool.close()


asyncio.run(main())
