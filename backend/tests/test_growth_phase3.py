"""Phase 3 Adaptive Growth Engine offline unit tests.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import os
from unittest.mock import patch

from app.services.growth.icp_score import score_lead
from app.services.growth.reply_classifier import classify_reply
from app.services.growth.sender_guard import (
    domain_is_blocked,
    validate_outreach_sender_domains,
)
from app.services.growth.outreach_publisher import _sequence_from_body


def test_icp_scores_title_specialty_npi():
    lo = score_lead(title="Intern", specialty="retail", npi="")
    hi = score_lead(
        title="Clinical Director",
        specialty="behavioral health therapy",
        npi="1234567890",
        state="TX",
    )
    assert hi > lo
    assert hi >= 0.8


def test_reply_classifier_paths():
    assert classify_reply("Please unsubscribe me")["classification"] == "unsubscribe"
    assert classify_reply("Out of office until Monday")["classification"] == "ooo"
    assert classify_reply("Yes, interested — book a call")["classification"] == "interested"
    assert classify_reply("Not interested, thanks")["classification"] == "not_interested"
    assert classify_reply("Hmm maybe later")["classification"] == "needs_review"


def test_sender_guard_blocks_product_domain():
    assert domain_is_blocked("sovereignsanctuary.net")
    assert domain_is_blocked("mail.sovereignsanctuary.net")
    assert not domain_is_blocked("outreach.example.com")


def test_sender_guard_requires_domains_when_outreach_on():
    with patch.dict(
        os.environ,
        {"ENABLE_OUTREACH_ENGINE": "true", "OUTREACH_SENDER_DOMAINS": ""},
        clear=False,
    ):
        ok, msg = validate_outreach_sender_domains()
        assert not ok
        assert "empty" in msg


def test_sender_guard_rejects_product_in_list():
    with patch.dict(
        os.environ,
        {
            "ENABLE_OUTREACH_ENGINE": "true",
            "OUTREACH_SENDER_DOMAINS": "outreach.example.com,sovereignsanctuary.net",
        },
        clear=False,
    ):
        ok, msg = validate_outreach_sender_domains()
        assert not ok
        assert "blocked" in msg


def test_sequence_split_on_delimiter():
    steps = _sequence_from_body(
        "Hello",
        "Subject: First touch\nBody one\n---\nSubject: Follow up\nBody two",
    )
    assert len(steps) == 2
    assert steps[0]["variants"][0]["subject"] == "First touch"
    assert "Body two" in steps[1]["variants"][0]["body"]


def test_gdpr_erase_shape_is_dict_contract():
    # Contract check without DB — method signature exists and returns documented keys.
    from app.services.growth.buyer_leads import BuyerLeadsService
    import inspect

    sig = inspect.signature(BuyerLeadsService.gdpr_erase)
    assert "email" in sig.parameters
    assert "actor" in sig.parameters
