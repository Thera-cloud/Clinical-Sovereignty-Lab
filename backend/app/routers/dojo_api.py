"""
DOJO Assessment API
REST endpoints for PDF assessment generation, download, upload scoring, history,
and JUDGE case document management.
"""

import json
import os
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, UploadFile, File, HTTPException
from fastapi.responses import FileResponse

from app.services.api_server import require_coach

router = APIRouter(prefix="/api/dojo", tags=["dojo"], dependencies=[Depends(require_coach)])

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
VAULT_ROOT = DATA_DIR / "Vaults"


def _get_director():
    """Lazy-load Night School Director."""
    from app.services.night_school_director import create_night_school_director
    return create_night_school_director(VAULT_ROOT)


@router.post("/preview-assessment")
async def preview_assessment(
    coach_id: str = Form(...),
    mode: str = Form(...),
    focus_areas: str = Form("all"),
    num_questions: int = Form(20),
    difficulty: str = Form("medium"),
    coach_name: str = Form(""),
):
    """Preview assessment questions WITHOUT generating the PDF.
    Returns questions as JSON so the coach can review before committing."""
    try:
        director = _get_director()
        result = director.preview_dojo_assessment(
            mode=mode,
            focus_areas=focus_areas,
            num_questions=num_questions,
            difficulty=difficulty,
            coach_id=coach_id,
            coach_name=coach_name,
        )
        return result
    except Exception as e:
        raise HTTPException(500, f"Preview failed: {e}")


@router.post("/generate-assessment")
async def generate_assessment(
    coach_id: str = Form(...),
    mode: str = Form(...),
    focus_areas: str = Form("all"),
    num_questions: int = Form(20),
    difficulty: str = Form("medium"),
    coach_name: str = Form(""),
    preview_id: str = Form(""),
):
    """Generate a PDF assessment for the DOJO. 
    If preview_id is provided, uses the cached questions from preview.
    Otherwise generates fresh questions."""
    try:
        director = _get_director()
        result = director.generate_dojo_assessment(
            mode=mode,
            focus_areas=focus_areas,
            num_questions=num_questions,
            difficulty=difficulty,
            coach_id=coach_id,
            coach_name=coach_name,
            preview_id=preview_id,
        )
        
        if result.get("error"):
            return {
                "test_id": result["test_id"],
                "questions": result.get("questions", []),
                "error": result["error"],
                "metadata": result.get("metadata", {}),
            }
        
        return {
            "test_id": result["test_id"],
            "download_url": f"/api/dojo/download-assessment/{result['test_id']}",
            "metadata": result.get("metadata", {}),
        }
    except Exception as e:
        raise HTTPException(500, f"Assessment generation failed: {e}")


@router.get("/download-assessment/{test_id}")
async def download_assessment(test_id: str):
    """Download a generated PDF assessment."""
    # Search for the PDF across all mode directories
    assessments_root = VAULT_ROOT / "Admin" / "night_school" / "dojo_assessments"
    if not assessments_root.exists():
        # Try alternate location
        assessments_root = DATA_DIR / "dojo_assessments"
    
    for pdf_path in assessments_root.rglob(f"{test_id}.pdf"):
        return FileResponse(
            path=str(pdf_path),
            media_type="application/pdf",
            filename=f"{test_id}.pdf",
            headers={"Content-Disposition": f"attachment; filename={test_id}.pdf"}
        )
    
    raise HTTPException(404, f"Assessment {test_id} not found")


@router.get("/download-export/{file_id}")
async def download_export(file_id: str):
    """Download a generated Gantt chart PDF or Excel export from the Dojo."""
    export_dir = DATA_DIR / "dojo_exports"
    if not export_dir.exists():
        raise HTTPException(404, f"Export {file_id} not found")

    # Check for PDF
    pdf_path = export_dir / f"{file_id}.pdf"
    if pdf_path.exists():
        return FileResponse(
            path=str(pdf_path),
            media_type="application/pdf",
            filename=f"{file_id}.pdf",
            headers={"Content-Disposition": f"attachment; filename={file_id}.pdf"}
        )

    # Check for Excel
    xlsx_path = export_dir / f"{file_id}.xlsx"
    if xlsx_path.exists():
        return FileResponse(
            path=str(xlsx_path),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=f"{file_id}.xlsx",
            headers={"Content-Disposition": f"attachment; filename={file_id}.xlsx"}
        )

    raise HTTPException(404, f"Export {file_id} not found")


@router.post("/score-assessment")
async def score_assessment(
    file: UploadFile = File(...),
    coach_id: str = Form(...),
    test_id: str = Form(...),
):
    """Score a completed assessment by reading the uploaded PDF and comparing to answer key."""
    try:
        # Read uploaded PDF
        content = await file.read()
        
        # Extract text from PDF
        answer_text = ""
        try:
            from pypdf import PdfReader
            import io
            reader = PdfReader(io.BytesIO(content))
            for page in reader.pages:
                answer_text += page.extract_text() or ""
        except ImportError:
            try:
                from PyPDF2 import PdfReader
                import io
                reader = PdfReader(io.BytesIO(content))
                for page in reader.pages:
                    answer_text += page.extract_text() or ""
            except ImportError:
                # Fallback: treat as text
                answer_text = content.decode("utf-8", errors="ignore")
        
        director = _get_director()
        result = director.score_dojo_assessment(
            test_id=test_id,
            coach_id=coach_id,
            answer_text=answer_text,
        )
        
        if result.get("error"):
            raise HTTPException(404, result["error"])
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Scoring failed: {e}")


@router.get("/assessment-history/{coach_id}")
async def get_assessment_history(coach_id: str, mode: str = "all"):
    """Get historical assessment scores for a coach."""
    progress_dir = VAULT_ROOT / "Admin" / "night_school" / "dojo_progress"
    if not progress_dir.exists():
        progress_dir = DATA_DIR / "dojo_progress"
    
    history = []
    
    if mode == "all":
        modes = ["therapist", "project_pm", "business", "cnc", "mcat", "teacher", "judge"]
    else:
        modes = [mode.lower()]
    
    for m in modes:
        progress_file = progress_dir / f"{m}.json"
        if progress_file.exists():
            try:
                with open(progress_file, 'r') as f:
                    data = json.load(f)
                coach_entries = [e for e in data if e.get("coach_id") == coach_id]
                history.extend(coach_entries)
            except Exception:
                pass
    
    # Sort by date
    history.sort(key=lambda x: x.get("scored_at", ""), reverse=True)
    
    return {
        "coach_id": coach_id,
        "mode": mode,
        "history": history,
        "total_assessments": len(history),
    }


# =============================================================================
# JUDGE DOJO — Case Document Management
# =============================================================================

def _cases_dir(coach_id: str) -> Path:
    """Get the case documents directory for a coach."""
    return VAULT_ROOT / "Coaches" / coach_id / "Documents" / "cases"


@router.post("/upload-case")
async def upload_case(
    file: UploadFile = File(...),
    coach_id: str = Form(...),
    case_title: str = Form(...),
    case_type: str = Form("civil"),
):
    """Upload a case document (PDF) for the JUDGE DOJO.
    Extracts text for Judge Nate to reference during sessions.
    case_type: civil | criminal | appellate | constitutional"""
    valid_types = ["civil", "criminal", "appellate", "constitutional"]
    if case_type.lower() not in valid_types:
        raise HTTPException(400, f"Invalid case_type. Must be one of: {', '.join(valid_types)}")

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted for case uploads")

    case_id = f"CASE-{uuid.uuid4().hex[:8].upper()}"
    cases_path = _cases_dir(coach_id)
    cases_path.mkdir(parents=True, exist_ok=True)

    # Save original PDF
    content = await file.read()
    pdf_path = cases_path / f"{case_id}.pdf"
    pdf_path.write_bytes(content)

    # Extract text from PDF
    extracted_text = ""
    try:
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(content))
        for page in reader.pages:
            extracted_text += (page.extract_text() or "") + "\n"
    except ImportError:
        try:
            from PyPDF2 import PdfReader
            import io
            reader = PdfReader(io.BytesIO(content))
            for page in reader.pages:
                extracted_text += (page.extract_text() or "") + "\n"
        except ImportError:
            extracted_text = "[PDF text extraction unavailable — install pypdf]"

    # Save extracted text + metadata as JSON
    meta = {
        "case_id": case_id,
        "case_title": case_title,
        "case_type": case_type.lower(),
        "original_filename": file.filename,
        "uploaded_at": datetime.now().isoformat(),
        "coach_id": coach_id,
        "page_count": len(extracted_text.split("\n\n")),
        "text_length": len(extracted_text),
        "extracted_text": extracted_text.strip(),
    }
    text_path = cases_path / f"{case_id}_text.json"
    with open(text_path, "w") as f:
        json.dump(meta, f, indent=2)

    return {
        "case_id": case_id,
        "case_title": case_title,
        "case_type": case_type.lower(),
        "uploaded_at": meta["uploaded_at"],
        "text_length": meta["text_length"],
        "message": f"Case '{case_title}' uploaded successfully. Judge Nate can now reference it in sessions.",
    }


@router.get("/cases/{coach_id}")
async def list_cases(coach_id: str):
    """List all uploaded case documents for a JUDGE DOJO coach."""
    cases_path = _cases_dir(coach_id)
    if not cases_path.exists():
        return {"coach_id": coach_id, "cases": [], "total": 0}

    cases = []
    for json_file in sorted(cases_path.glob("*_text.json"), reverse=True):
        try:
            with open(json_file, "r") as f:
                meta = json.load(f)
            cases.append({
                "case_id": meta["case_id"],
                "case_title": meta["case_title"],
                "case_type": meta["case_type"],
                "uploaded_at": meta["uploaded_at"],
                "text_length": meta.get("text_length", 0),
            })
        except Exception:
            pass

    return {"coach_id": coach_id, "cases": cases, "total": len(cases)}


@router.delete("/cases/{coach_id}/{case_id}")
async def delete_case(coach_id: str, case_id: str):
    """Delete a case document from the JUDGE DOJO case library."""
    cases_path = _cases_dir(coach_id)
    pdf_path = cases_path / f"{case_id}.pdf"
    text_path = cases_path / f"{case_id}_text.json"

    if not pdf_path.exists() and not text_path.exists():
        raise HTTPException(404, f"Case {case_id} not found for coach {coach_id}")

    if pdf_path.exists():
        pdf_path.unlink()
    if text_path.exists():
        text_path.unlink()

    return {"message": f"Case {case_id} deleted successfully", "case_id": case_id}


@router.get("/case-text/{coach_id}/{case_id}")
async def get_case_text(coach_id: str, case_id: str):
    """Get the extracted text of a case document for use in DOJO sessions.
    This is what gets injected into Judge Nate's system prompt."""
    text_path = _cases_dir(coach_id) / f"{case_id}_text.json"
    if not text_path.exists():
        raise HTTPException(404, f"Case {case_id} not found")

    with open(text_path, "r") as f:
        meta = json.load(f)

    return {
        "case_id": meta["case_id"],
        "case_title": meta["case_title"],
        "case_type": meta["case_type"],
        "extracted_text": meta.get("extracted_text", ""),
    }
