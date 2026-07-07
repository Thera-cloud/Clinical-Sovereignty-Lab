"""
Public Trial Funnel — unsubscribe REST pair (GET confirmation page + POST
mutate). See .cursor/plans/public_trial_funnel_4200095c.plan.md, Phase 3
re-engagement / P1 retention ("trial-email-reengagement").

Unauthenticated by design: the token itself is the credential. Per the plan's
own framing, the GET must never mutate (mail-scanner / link-preview prefetch
safety) — only the POST, submitted by the confirmation page's own button, may
set `unsubscribed_at`.

What does this expose to someone with no account and bad intent? A valid
token reveals only a masked email address (e.g. "j***n@example.com") on the
GET page — never the raw address, never any other lead metadata. An invalid
or expired token returns a generic "not valid" page in both GET and POST,
so this endpoint cannot be used to enumerate which emails have leads.
"""
import logging
import time
from typing import Dict, List

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app.services.public_trial_gate import confirm_unsubscribe, lookup_unsubscribe_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/public-trial", tags=["public-trial"])

# Same per-IP rate-limit discipline as registration_checkout.py — this is an
# unauthenticated, token-guessing-adjacent surface.
_rate_hits: Dict[str, List[float]] = {}
_RATE_WINDOW_S = 60
_RATE_MAX = 10


def _rate_limited(ip: str) -> bool:
    now = time.time()
    hits = [t for t in _rate_hits.get(ip, []) if now - t < _RATE_WINDOW_S]
    hits.append(now)
    _rate_hits[ip] = hits
    return len(hits) > _RATE_MAX


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


_PAGE_STYLE = (
    "body{font-family:sans-serif;background:#050505;color:#E8D5A3;display:flex;"
    "align-items:center;justify-content:center;min-height:100vh;margin:0;}"
    ".card{max-width:420px;padding:32px;text-align:center;}"
    "button{padding:12px 24px;background:#C9A962;color:#050505;border:none;"
    "border-radius:6px;font-size:16px;cursor:pointer;}"
)

_INVALID_PAGE = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Link no longer valid</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{_PAGE_STYLE}</style></head>
<body><div class="card"><h2>This link is no longer valid</h2>
<p>It may have expired or already been used.</p></div></body></html>"""


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return "your email"
    name, _, domain = email.partition("@")
    if len(name) <= 2:
        masked = (name[0] + "*") if name else "*"
    else:
        masked = name[0] + "*" * (len(name) - 2) + name[-1]
    return f"{masked}@{domain}"


def _confirm_page(email_masked: str, already_unsubscribed: bool, token: str) -> str:
    if already_unsubscribed:
        body = "<h2>You're already unsubscribed</h2><p>No further emails will be sent.</p>"
    else:
        body = (
            "<h2>Stop these emails?</h2>"
            f"<p>We'll stop emailing {email_masked} about your Little Nate trial conversation.</p>"
            '<form method="POST" action="/api/public-trial/unsubscribe">'
            f'<input type="hidden" name="token" value="{token}">'
            '<button type="submit">Yes, stop these emails</button>'
            "</form>"
        )
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Unsubscribe</title>'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<style>{_PAGE_STYLE}</style></head>"
        f'<body><div class="card">{body}</div></body></html>'
    )


_DONE_PAGE = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Unsubscribed</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{_PAGE_STYLE}</style></head>
<body><div class="card"><h2>You're unsubscribed</h2>
<p>No further emails will be sent.</p></div></body></html>"""


@router.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe_confirm_page(token: str, request: Request):
    """Read-only. MUST NOT mutate — this must be safe against a mail
    scanner or link-preview bot issuing a bare GET with no human follow-up."""
    if _rate_limited(_client_ip(request)):
        return HTMLResponse(_INVALID_PAGE, status_code=429)

    row = await lookup_unsubscribe_token(token)
    if not row:
        return HTMLResponse(_INVALID_PAGE, status_code=404)

    return HTMLResponse(_confirm_page(_mask_email(row["email"]), row["already_unsubscribed"], token))


@router.post("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe_mutate(request: Request, token: str = Form(...)):
    """The only path that sets `unsubscribed_at`. Form-encoded (not JSON) —
    this is submitted directly by the confirmation page's HTML <form> button,
    never fired by a bare GET."""
    if _rate_limited(_client_ip(request)):
        return HTMLResponse(_INVALID_PAGE, status_code=429)

    ok = await confirm_unsubscribe(token)
    if ok:
        return HTMLResponse(_DONE_PAGE)

    # Either an invalid token, or a token that was already unsubscribed
    # (confirm_unsubscribe's WHERE unsubscribed_at IS NULL guard means a
    # double-submit returns False even though the token itself is real) —
    # look it up once more to give the "already unsubscribed" copy when
    # applicable, otherwise the generic invalid-link page either way.
    row = await lookup_unsubscribe_token(token)
    if row:
        return HTMLResponse(_confirm_page(_mask_email(row["email"]), True, token))
    return HTMLResponse(_INVALID_PAGE, status_code=404)
