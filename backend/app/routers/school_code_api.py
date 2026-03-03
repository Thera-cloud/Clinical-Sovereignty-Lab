"""
School Discount Code API — Student verification and enrollment.

Supports FAFSA (6-digit), CEEB/CollegeBoard (6-digit), CSS Profile (4-digit).
Verification via ID.me or National Student Clearinghouse (NSC).
All subscription fees charged to the student's own account.
"""

import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from app.services.api_server import get_current_user, require_admin

logger = logging.getLogger("nate.school_code_api")

router = APIRouter(
    prefix="/api/billing/school-codes",
    tags=["school-codes"],
)

CODE_PATTERNS = {
    "FAFSA": re.compile(r"^\d{6}$"),
    "CEEB": re.compile(r"^\d{6}$"),
    "CSS_PROFILE": re.compile(r"^\d{4}$"),
}

CODE_TYPE_LABELS = {
    "FAFSA": "FAFSA Federal School Code",
    "CEEB": "CEEB / CollegeBoard Code",
    "CSS_PROFILE": "CSS Profile Code",
}


class CreateSchoolCodeRequest(BaseModel):
    code: str
    code_type: str
    institution_name: str
    discount_pct: int = 20
    max_enrollments: Optional[int] = None

    @field_validator("code_type")
    @classmethod
    def validate_code_type(cls, v):
        if v not in CODE_PATTERNS:
            raise ValueError(f"code_type must be one of: {', '.join(CODE_PATTERNS)}")
        return v

    @field_validator("discount_pct")
    @classmethod
    def validate_discount(cls, v):
        if v < 1 or v > 100:
            raise ValueError("discount_pct must be between 1 and 100")
        return v


class StudentVerificationRequest(BaseModel):
    school_code_id: str
    student_full_name: str
    date_of_birth: str
    institution_name: str
    attendance_start: str
    attendance_end: Optional[str] = None
    verification_method: str

    @field_validator("verification_method")
    @classmethod
    def validate_method(cls, v):
        if v not in ("ID_ME", "NSC"):
            raise ValueError("verification_method must be ID_ME or NSC")
        return v


class VerifyCallbackRequest(BaseModel):
    verification_id: str
    status: str
    external_id: Optional[str] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        if v not in ("verified", "rejected"):
            raise ValueError("status must be verified or rejected")
        return v


# ============================================================
# Admin endpoints
# ============================================================

@router.post("", dependencies=[Depends(require_admin)])
async def create_school_code(req: CreateSchoolCodeRequest, request: Request, user: Dict = Depends(require_admin)):
    """Admin creates a school discount code."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    pattern = CODE_PATTERNS.get(req.code_type)
    if pattern and not pattern.match(req.code):
        expected = "6 digits" if req.code_type in ("FAFSA", "CEEB") else "4 digits"
        raise HTTPException(400, f"{CODE_TYPE_LABELS[req.code_type]} must be {expected}")

    async with db.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM school_discount_codes WHERE code = $1 AND code_type = $2",
            req.code, req.code_type,
        )
        if existing:
            raise HTTPException(400, f"Code {req.code} ({req.code_type}) already exists")

        row = await conn.fetchrow(
            """INSERT INTO school_discount_codes
                   (code, code_type, institution_name, discount_pct, max_enrollments, created_by)
               VALUES ($1, $2, $3, $4, $5, $6)
               RETURNING id, code, code_type, institution_name, discount_pct, status""",
            req.code, req.code_type, req.institution_name, req.discount_pct,
            req.max_enrollments, user.get("hardware_id", "admin"),
        )

    return {
        "id": str(row["id"]),
        "code": row["code"],
        "code_type": row["code_type"],
        "institution_name": row["institution_name"],
        "discount_pct": row["discount_pct"],
        "status": row["status"],
    }


@router.get("", dependencies=[Depends(require_admin)])
async def list_school_codes(request: Request, user: Dict = Depends(require_admin)):
    """List all school discount codes with enrollment counts."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        return {"codes": [], "count": 0}

    async with db.acquire() as conn:
        rows = await conn.fetch(
            """SELECT sc.id, sc.code, sc.code_type, sc.institution_name,
                      sc.discount_pct, sc.status, sc.max_enrollments, sc.created_at,
                      COUNT(sv.id) FILTER (WHERE sv.verification_status = 'verified') as verified_count,
                      COUNT(sv.id) FILTER (WHERE sv.verification_status = 'pending') as pending_count
               FROM school_discount_codes sc
               LEFT JOIN student_verifications sv ON sv.school_code_id = sc.id
               GROUP BY sc.id
               ORDER BY sc.created_at DESC"""
        )

    codes = []
    for r in rows:
        codes.append({
            "id": str(r["id"]),
            "code": r["code"],
            "code_type": r["code_type"],
            "code_type_label": CODE_TYPE_LABELS.get(r["code_type"], r["code_type"]),
            "institution_name": r["institution_name"],
            "discount_pct": r["discount_pct"],
            "status": r["status"],
            "max_enrollments": r["max_enrollments"],
            "verified_students": r["verified_count"],
            "pending_students": r["pending_count"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        })

    return {"codes": codes, "count": len(codes)}


@router.put("/{code_id}/status", dependencies=[Depends(require_admin)])
async def update_code_status(code_id: str, status: str, request: Request, user: Dict = Depends(require_admin)):
    """Suspend or reactivate a school code."""
    if status not in ("active", "suspended", "expired"):
        raise HTTPException(400, "Status must be active, suspended, or expired")

    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    async with db.acquire() as conn:
        result = await conn.execute(
            "UPDATE school_discount_codes SET status = $1, updated_at = NOW() WHERE id = $2::uuid",
            status, code_id,
        )
        if result == "UPDATE 0":
            raise HTTPException(404, "School code not found")

    return {"status": status}


@router.get("/{code_id}/students", dependencies=[Depends(require_admin)])
async def list_enrolled_students(code_id: str, request: Request, user: Dict = Depends(require_admin)):
    """List students enrolled under a school code."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        return {"students": [], "count": 0}

    async with db.acquire() as conn:
        rows = await conn.fetch(
            """SELECT sv.id, sv.student_full_name, sv.date_of_birth, sv.institution_name,
                      sv.attendance_start, sv.attendance_end,
                      sv.verification_method, sv.verification_status,
                      sv.verified_at, sv.expires_at, sv.created_at,
                      u.username, u.profile_data->>'email' as email
               FROM student_verifications sv
               LEFT JOIN users u ON u.id = sv.user_id
               WHERE sv.school_code_id = $1::uuid
               ORDER BY sv.created_at DESC""",
            code_id,
        )

    students = []
    for r in rows:
        students.append({
            "id": str(r["id"]),
            "username": r["username"],
            "email": r["email"],
            "student_full_name": r["student_full_name"],
            "date_of_birth": r["date_of_birth"].isoformat() if r["date_of_birth"] else None,
            "institution_name": r["institution_name"],
            "attendance_start": r["attendance_start"].isoformat() if r["attendance_start"] else None,
            "attendance_end": r["attendance_end"].isoformat() if r["attendance_end"] else None,
            "verification_method": r["verification_method"],
            "verification_status": r["verification_status"],
            "verified_at": r["verified_at"].isoformat() if r["verified_at"] else None,
            "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
        })

    return {"students": students, "count": len(students)}


# ============================================================
# Student-facing endpoints (authenticated user)
# ============================================================

@router.post("/verify/{code}")
async def verify_school_code(code: str, request: Request, user: Dict = Depends(get_current_user)):
    """Student verifies a school code exists and is active."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, code, code_type, institution_name, discount_pct, status, max_enrollments
               FROM school_discount_codes WHERE code = $1 AND status = 'active'""",
            code,
        )

    if not row:
        raise HTTPException(404, "Invalid or inactive school code")

    if row["max_enrollments"]:
        async with db.acquire() as conn:
            enrolled = await conn.fetchval(
                """SELECT COUNT(*) FROM student_verifications
                   WHERE school_code_id = $1 AND verification_status = 'verified'""",
                row["id"],
            )
            if enrolled >= row["max_enrollments"]:
                raise HTTPException(400, "This school code has reached its enrollment cap")

    return {
        "valid": True,
        "code": row["code"],
        "code_type": row["code_type"],
        "code_type_label": CODE_TYPE_LABELS.get(row["code_type"], row["code_type"]),
        "institution_name": row["institution_name"],
        "discount_pct": row["discount_pct"],
        "verification_required": True,
        "accepted_methods": ["ID_ME", "NSC"],
        "required_info": [
            "student_full_name",
            "date_of_birth",
            "institution_name",
            "attendance_start",
            "attendance_end (optional)",
        ],
    }


@router.post("/enroll")
async def enroll_student(req: StudentVerificationRequest, request: Request, user: Dict = Depends(get_current_user)):
    """Student submits enrollment with verification info. Pending until ID.me/NSC callback."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    hw_id = user.get("hardware_id", "")
    username = user.get("username", "")

    async with db.acquire() as conn:
        user_row = await conn.fetchrow("SELECT id FROM users WHERE username = $1", username)
        if not user_row:
            raise HTTPException(404, "User not found")
        user_uuid = user_row["id"]

        code_row = await conn.fetchrow(
            "SELECT id, status, institution_name, max_enrollments FROM school_discount_codes WHERE id = $1::uuid",
            req.school_code_id,
        )
        if not code_row:
            raise HTTPException(404, "School code not found")
        if code_row["status"] != "active":
            raise HTTPException(400, f"School code is {code_row['status']}")

        if code_row["max_enrollments"]:
            enrolled = await conn.fetchval(
                "SELECT COUNT(*) FROM student_verifications WHERE school_code_id = $1 AND verification_status = 'verified'",
                code_row["id"],
            )
            if enrolled >= code_row["max_enrollments"]:
                raise HTTPException(400, "Enrollment cap reached")

        existing = await conn.fetchrow(
            "SELECT id, verification_status FROM student_verifications WHERE user_id = $1 AND school_code_id = $2",
            user_uuid, code_row["id"],
        )
        if existing and existing["verification_status"] == "verified":
            raise HTTPException(400, "Already verified for this school code")

        try:
            dob = datetime.strptime(req.date_of_birth, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "date_of_birth must be YYYY-MM-DD format")

        try:
            att_start = datetime.strptime(req.attendance_start, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "attendance_start must be YYYY-MM-DD format")

        att_end = None
        if req.attendance_end:
            try:
                att_end = datetime.strptime(req.attendance_end, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(400, "attendance_end must be YYYY-MM-DD format")

        if existing:
            await conn.execute(
                """UPDATE student_verifications
                   SET student_full_name = $1, date_of_birth = $2, institution_name = $3,
                       attendance_start = $4, attendance_end = $5, verification_method = $6,
                       verification_status = 'pending', updated_at = NOW()
                   WHERE id = $7""",
                req.student_full_name, dob, req.institution_name,
                att_start, att_end, req.verification_method, existing["id"],
            )
            verification_id = str(existing["id"])
        else:
            row = await conn.fetchrow(
                """INSERT INTO student_verifications
                       (user_id, school_code_id, student_full_name, date_of_birth,
                        institution_name, attendance_start, attendance_end, verification_method)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                   RETURNING id""",
                user_uuid, code_row["id"], req.student_full_name, dob,
                req.institution_name, att_start, att_end, req.verification_method,
            )
            verification_id = str(row["id"])

    redirect_url = None
    if req.verification_method == "ID_ME":
        redirect_url = f"https://api.id.me/oauth/authorize?client_id=PLACEHOLDER&scope=student&redirect_uri=https://api.sovereignsanctuary.net/api/billing/school-codes/callback/idme&state={verification_id}"
    elif req.verification_method == "NSC":
        redirect_url = f"https://www.studentclearinghouse.org/verify?ref={verification_id}"

    return {
        "status": "pending",
        "verification_id": verification_id,
        "verification_method": req.verification_method,
        "redirect_url": redirect_url,
        "message": f"Please complete verification through {req.verification_method.replace('_', '.')}",
    }


@router.post("/callback/{provider}", dependencies=[Depends(require_admin)])
async def verification_callback(provider: str, req: VerifyCallbackRequest, request: Request):
    """Callback from ID.me or NSC after student verification completes."""
    if provider not in ("idme", "nsc"):
        raise HTTPException(400, "Unknown verification provider")

    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    async with db.acquire() as conn:
        sv = await conn.fetchrow(
            "SELECT id, user_id, school_code_id FROM student_verifications WHERE id = $1::uuid",
            req.verification_id,
        )
        if not sv:
            raise HTTPException(404, "Verification not found")

        if req.status == "verified":
            expires = datetime.now(timezone.utc) + timedelta(days=365)
            await conn.execute(
                """UPDATE student_verifications
                   SET verification_status = 'verified', verification_id = $1,
                       verified_at = NOW(), expires_at = $2, updated_at = NOW()
                   WHERE id = $3""",
                req.external_id, expires, sv["id"],
            )

            await conn.execute(
                "UPDATE users SET school_code_id = $1, student_verified = true, updated_at = NOW() WHERE id = $2",
                sv["school_code_id"], sv["user_id"],
            )

            logger.info("Student verification approved: user_id=%s, school_code=%s", sv["user_id"], sv["school_code_id"])
        else:
            await conn.execute(
                """UPDATE student_verifications
                   SET verification_status = 'rejected', verification_id = $1, updated_at = NOW()
                   WHERE id = $2""",
                req.external_id, sv["id"],
            )
            logger.info("Student verification rejected: user_id=%s", sv["user_id"])

    return {"status": req.status, "verification_id": req.verification_id}


@router.get("/my-status")
async def get_my_student_status(request: Request, user: Dict = Depends(get_current_user)):
    """Student checks their own verification status."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        return {"enrolled": False}

    username = user.get("username", "")
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT sv.verification_status, sv.verification_method, sv.verified_at,
                      sv.expires_at, sv.institution_name,
                      sc.code, sc.code_type, sc.discount_pct,
                      sc.institution_name as code_institution
               FROM student_verifications sv
               JOIN school_discount_codes sc ON sc.id = sv.school_code_id
               JOIN users u ON u.id = sv.user_id
               WHERE u.username = $1
               ORDER BY sv.created_at DESC LIMIT 1""",
            username,
        )

    if not row:
        return {"enrolled": False}

    return {
        "enrolled": True,
        "verification_status": row["verification_status"],
        "verification_method": row["verification_method"],
        "institution_name": row["institution_name"],
        "discount_pct": row["discount_pct"],
        "code": row["code"],
        "code_type": row["code_type"],
        "verified_at": row["verified_at"].isoformat() if row["verified_at"] else None,
        "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
    }


@router.get("/health")
async def school_codes_health(request: Request):
    """Health check for school codes subsystem."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        return {"status": "degraded", "reason": "no database"}

    try:
        async with db.acquire() as conn:
            tables = await conn.fetchval(
                """SELECT COUNT(*) FROM information_schema.tables
                   WHERE table_name IN ('school_discount_codes', 'student_verifications')"""
            )
        return {
            "status": "ok" if tables == 2 else "degraded",
            "tables_found": tables,
            "expected_tables": 2,
            "code_types": list(CODE_TYPE_LABELS.keys()),
            "verification_methods": ["ID_ME", "NSC"],
        }
    except Exception as e:
        return {"status": "error", "reason": str(e)}
