"""Classroom Audit Test — exercises the full PhD assessment pipeline."""
import asyncio
import asyncpg
import os
import json
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/opt/clinical-sovereignty-lab/backend")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


async def run_audit():
    print("=" * 60)
    print("CLASSROOM AUDIT TEST")
    print("=" * 60)

    db_url = os.getenv(
        "DATABASE_URL",
        "postgresql://nate_admin:nate_admin_2025@postgres:5432/little_nate",
    )
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)

    # Step 1: Verify test analysis exists
    print("\n[1] Verifying test analysis exists...")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT session_id, coach_id, client_id, client_name, status "
            "FROM classroom_session_analyses WHERE session_id = $1",
            "audit_test_session_001",
        )
    if row:
        print(
            f"   OK Found: {row['session_id']} | coach={row['coach_id']} "
            f"| client={row['client_name']} | status={row['status']}"
        )
    else:
        print("   FAIL Test analysis not found!")
        return

    from app.services.pg_data_helpers import (
        get_classroom_analysis_pg,
        update_classroom_analysis_pg,
        get_classroom_progress_pg,
        place_assessment_in_folder_pg,
        get_classroom_context_for_client_pg,
        get_classroom_lived_wisdom_pg,
        get_master_coherence_context_pg,
        get_master_for_assistant_pg,
    )

    # Step 2: Test get_classroom_analysis_pg
    print("\n[2] Testing get_classroom_analysis_pg...")
    analysis = await get_classroom_analysis_pg(pool, "audit_test_session_001")
    if analysis:
        mk = list((analysis.get("metrics") or {}).keys())[:5]
        print(f"   OK Analysis loaded: status={analysis.get('status')}, metrics keys={mk}")
    else:
        print("   FAIL Failed to load analysis from PG")
        return

    # Step 3: Test PhD assessment generation
    print("\n[3] Testing PhD assessment generation via Azure...")
    from app.services.classroom_analyzer import (
        generate_phd_assessment_async,
        format_assessment_as_markdown,
    )

    dojo_keys = ["THERAPIST", "COUNSELOR"]
    transcript = (analysis.get("payload") or {}).get("transcript_text", "")
    metrics = analysis.get("metrics") or {}
    assessments = await generate_phd_assessment_async(
        dojo_keys=dojo_keys,
        transcript_text=transcript,
        metrics=metrics,
        coach_name="Audit Lawyer 1",
        client_name="Audit Student 1",
        initial_analysis=analysis.get("payload"),
    )
    if assessments:
        print(f"   OK Assessment generated: {list(assessments.keys())}")
        for dk in dojo_keys:
            da = assessments.get(dk, {})
            summary = str(da.get("summary", ""))[:80]
            print(f"      {dk}: score={da.get('score')}, grade={da.get('letter_grade')}, summary={summary}")
        combined = assessments.get("combined", {})
        print(f"      Combined: score={combined.get('score')}, tp={combined.get('therapeutic_presence_score')}")
    else:
        print("   WARN Assessment returned empty (Azure may be unavailable)")

    # Step 4: Update analysis with results
    print("\n[4] Updating analysis with DOJO selection and assessment...")
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d%H%M")
    doc_id = f"classroom_assessment_audit_test_session_001_{ts}"
    ok = await update_classroom_analysis_pg(
        pool,
        "audit_test_session_001",
        status="completed",
        selected_dojos=dojo_keys,
        assessments=assessments,
        therapeutic_presence_score=assessments.get("combined", {}).get(
            "therapeutic_presence_score", 7.0
        ),
        final_assessment_doc_id=doc_id,
        completed_at=now,
    )
    print(f"   {'OK' if ok else 'FAIL'} Update result: {ok}")

    updated = await get_classroom_analysis_pg(pool, "audit_test_session_001")
    print(
        f"   Status: {updated.get('status')}, DOJOs: {updated.get('selected_dojos')}, "
        f"Score: {updated.get('therapeutic_presence_score')}"
    )

    # Step 5: Test FOLDER placement
    print("\n[5] Testing FOLDER placement...")
    md_doc = format_assessment_as_markdown(
        assessments, "Audit Lawyer 1", "Audit Student 1", dojo_keys, "audit_test_session_001"
    )
    file_id = await place_assessment_in_folder_pg(
        pool, "audit_lawyer_1_hw", "audit_student_1_hw", "Audit Student 1", doc_id, md_doc
    )
    print(f"   {'OK' if file_id else 'FAIL'} Placed in folder: file_id={file_id}")
    print(f"   Document size: {len(md_doc)} chars")
    print(f"   First 200 chars: {md_doc[:200]}")

    # Step 6: Test YOUR PROGRESS
    print("\n[6] Testing YOUR PROGRESS...")
    progress = await get_classroom_progress_pg(pool, "audit_lawyer_1_hw")
    print(
        f"   OK Progress: total={progress['total_sessions_reviewed']}, "
        f"avg_score={progress['average_presence_score']}, "
        f"pending={progress['pending']}, completed={progress['completed']}"
    )

    # Step 7: Test client context for Nate
    print("\n[7] Testing client context injection for Nate chat...")
    client_ctx = await get_classroom_context_for_client_pg(pool, "audit_student_1_hw")
    preview = client_ctx[:200] if client_ctx else "empty"
    print(f"   {'OK' if client_ctx else 'WARN'} Client context: {preview}")

    # Step 8: Test lived wisdom Q&A
    print("\n[8] Testing lived wisdom context...")
    wisdom = await get_classroom_lived_wisdom_pg(
        pool, "audit_lawyer_1_hw", client_id="audit_student_1_hw"
    )
    preview = wisdom[:200] if wisdom else "empty"
    print(f"   {'OK' if wisdom else 'WARN'} Lived wisdom: {preview}")

    # Step 9: Test master coherence context
    print("\n[9] Testing master coherence context...")
    master_id = await get_master_for_assistant_pg(pool, "audit_lawyer_1_hw")
    print(f"   Master for audit_lawyer_1_hw: {master_id}")
    if master_id:
        coherence = await get_master_coherence_context_pg(
            pool, master_id, "audit_lawyer_1_hw", "audit_student_1_hw"
        )
        preview = coherence[:200] if coherence else "empty"
        print(f"   {'OK' if coherence else 'WARN'} Coherence: {preview}")

    # Step 10: Verify folder files exist
    print("\n[10] Verifying FOLDER files...")
    async with pool.acquire() as conn:
        folder_files = await conn.fetch(
            """SELECT ff.filename, ff.file_type, ff.created_at
               FROM coach_folder_files ff
               JOIN coach_folders f ON ff.folder_id = f.id
               WHERE f.coach_id = $1 AND f.entity_id = $2
               ORDER BY ff.created_at DESC LIMIT 5""",
            "audit_lawyer_1_hw",
            "audit_student_1_hw",
        )
    if folder_files:
        for ff in folder_files:
            print(f"   OK {ff['filename']} ({ff['file_type']}, {ff['created_at']})")
    else:
        print("   WARN No folder files found")

    print("\n" + "=" * 60)
    print("AUDIT TEST COMPLETE")
    print("=" * 60)

    await pool.close()


if __name__ == "__main__":
    asyncio.run(run_audit())
