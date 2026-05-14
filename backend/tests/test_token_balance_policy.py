"""Regression: stale zero bucket columns vs authoritative token_balance."""

from app.services.token_balance_policy import split_balances_from_profile, total_balance


def test_split_reconciles_orphan_into_subscription():
    profile = {
        "token_balance": 50000,
        "subscription_token_balance": 0,
        "purchased_token_balance": 0,
    }
    sub, purch = split_balances_from_profile(profile)
    assert sub == 50000 and purch == 0
    assert total_balance(sub, purch) == 50000


def test_split_unchanged_when_buckets_match_total():
    profile = {
        "token_balance": 50000,
        "subscription_token_balance": 40000,
        "purchased_token_balance": 10000,
    }
    sub, purch = split_balances_from_profile(profile)
    assert sub == 40000 and purch == 10000


def test_split_legacy_missing_subscription_key():
    profile = {"token_balance": 30000, "purchased_token_balance": 5000}
    sub, purch = split_balances_from_profile(profile)
    assert sub == 25000 and purch == 5000


def test_split_clamps_buckets_when_overstated():
    profile = {
        "token_balance": 40000,
        "subscription_token_balance": 30000,
        "purchased_token_balance": 30000,
    }
    sub, purch = split_balances_from_profile(profile)
    assert sub + purch == 40000
    assert purch == 30000 and sub == 10000
