"""HoH token pool + family-id aliases (LetsGoLisa / LetsGoBill)."""

from app.services.family_token_payer import (
    FAMILY_HOH_CIRCLE_MONTHLY_CENTS,
    family_hoh_circle_cents,
    family_id_aliases,
    find_registry_profile,
    overlay_family_token_balance,
    resolve_token_payer_hardware_id,
)


def _west_registry():
    return {
        "client_LetsGoBill": {
            "profile": {
                "username": "LetsGoBill",
                "hardware_id": "CLIENT_LETSGOBILL_ID",
                "id": "85665740-3f37-4fdd-9454-08455320a1ff",
                "family_id": "FAM_0F708896",
                "family_uuid": "fe09e4b9-febb-45db-b83a-2d53087a1210",
                "family_role": "HEAD",
                "token_balance": 31020,
                "subscription_token_balance": 31020,
                "purchased_token_balance": 0,
                "tier": "TOP_TIER",
            }
        },
        "client_LetsGoLisa": {
            "profile": {
                "username": "LetsGoLisa",
                "hardware_id": "CLIENT_LETSGOLISA_ID",
                "family_id": "FAM_0F708896",
                "family_uuid": "fe09e4b9-febb-45db-b83a-2d53087a1210",
                "family_role": "SPOUSE",
                "head_of_household_id": "85665740-3f37-4fdd-9454-08455320a1ff",
                "token_balance": 10,
                "subscription_token_balance": 10,
                "purchased_token_balance": 0,
                "tier": "TOP_TIER",
            }
        },
    }


def test_spouse_payer_is_hoh_hardware_id():
    reg = _west_registry()
    assert (
        resolve_token_payer_hardware_id(reg, "CLIENT_LETSGOLISA_ID")
        == "CLIENT_LETSGOBILL_ID"
    )
    assert (
        resolve_token_payer_hardware_id(reg, "LetsGoLisa")
        == "CLIENT_LETSGOBILL_ID"
    )


def test_hoh_uuid_resolves_bill():
    key, prof = find_registry_profile(
        _west_registry(), "85665740-3f37-4fdd-9454-08455320a1ff"
    )
    assert key == "client_LetsGoBill"
    assert prof["hardware_id"] == "CLIENT_LETSGOBILL_ID"


def test_lisa_login_shows_household_pool():
    reg = _west_registry()
    lisa = dict(reg["client_LetsGoLisa"]["profile"])
    overlay_family_token_balance(lisa, reg)
    assert lisa["token_balance"] == 31020
    assert lisa["token_pool"] == "household"
    assert lisa["token_payer"] == "LetsGoBill"


def test_family_id_aliases_merge_code_and_uuid():
    aliases = family_id_aliases(
        "fe09e4b9-febb-45db-b83a-2d53087a1210", _west_registry()
    )
    assert "FAM_0F708896" in aliases
    assert "fe09e4b9-febb-45db-b83a-2d53087a1210" in aliases


def test_family_hoh_circle_is_30():
    assert FAMILY_HOH_CIRCLE_MONTHLY_CENTS == 3000
    assert family_hoh_circle_cents({"family_role": "HEAD"}) == 3000
    assert family_hoh_circle_cents({"family_role": ""}) == 14900
