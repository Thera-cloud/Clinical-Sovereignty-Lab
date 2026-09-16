from datetime import datetime, timezone
import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault(
    "JWT_SECRET",
    "test-only-receipt-validation-secret-at-least-32-bytes",
)

from app.routers import receipt_validation as receipts


@pytest.mark.asyncio
async def test_apple_subscription_requires_shared_secret(monkeypatch):
    monkeypatch.delenv("APPLE_SHARED_SECRET", raising=False)

    with pytest.raises(HTTPException) as exc:
        await receipts.verify_apple_receipt(
            receipts.AppleReceiptRequest(
                receipt_data="base64-receipt",
                user_id="audit_client",
                product_id="net.sovereignsanctuary.inner_chamber_monthly",
            ),
            SimpleNamespace(),
            {"username": "audit_client", "user_id": "CLIENT_AUDIT_ID"},
        )

    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_apple_receipt_uses_canonical_username_and_sandbox(monkeypatch):
    monkeypatch.setenv("APPLE_SHARED_SECRET", "test-secret")
    calls = []

    async def fake_verify(_client, url, payload):
        calls.append((url, payload))
        if url == receipts.APPLE_PRODUCTION_URL:
            return {"status": 21007}
        return {
            "status": 0,
            "latest_receipt_info": [
                {
                    "product_id":
                        "net.sovereignsanctuary.inner_chamber_monthly",
                    "expires_date_ms": str(
                        int(datetime.now(timezone.utc).timestamp() * 1000)
                        + 86_400_000
                    ),
                }
            ],
        }

    activated = {}

    async def fake_activate(_request, user_id, plan, source, product_id):
        activated.update(
            user_id=user_id,
            plan=plan,
            source=source,
            product_id=product_id,
        )

    monkeypatch.setattr(receipts, "_post_apple_verify", fake_verify)
    monkeypatch.setattr(receipts, "_activate_plan", fake_activate)

    result = await receipts.verify_apple_receipt(
        receipts.AppleReceiptRequest(
            receipt_data="base64-receipt",
            user_id="audit_client",
            product_id="net.sovereignsanctuary.inner_chamber_monthly",
        ),
        SimpleNamespace(),
        {"username": "audit_client", "user_id": "CLIENT_AUDIT_ID"},
    )

    assert [call[0] for call in calls] == [
        receipts.APPLE_PRODUCTION_URL,
        receipts.APPLE_SANDBOX_URL,
    ]
    assert calls[0][1]["password"] == "test-secret"
    assert activated["user_id"] == "audit_client"
    assert result["status"] == "verified"
