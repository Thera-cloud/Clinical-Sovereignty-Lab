"""
USPS Address Validation Service
Uses USPS Web Tools API to verify and standardize addresses.
Registration: https://www.usps.com/business/web-tools-apis/

Env var required: USPS_USER_ID
"""

import os
import xml.etree.ElementTree as ET
from typing import Tuple, Dict, Optional
import aiohttp
import logging

logger = logging.getLogger(__name__)

USPS_API_URL = "https://secure.shippingapis.com/ShippingAPI.dll"
USPS_USER_ID = os.getenv("USPS_USER_ID", "")


def build_address_xml(street: str, city: str, state: str, zip_code: str, street2: str = "") -> str:
    """Build the XML request payload for USPS Address Validation API."""
    # Escape XML special characters
    def esc(s: str) -> str:
        return (s.replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;")
                 .replace('"', "&quot;")
                 .replace("'", "&apos;"))
    
    xml = (
        f'<AddressValidateRequest USERID="{esc(USPS_USER_ID)}">'
        f'<Revision>1</Revision>'
        f'<Address ID="0">'
        f'<Address1>{esc(street2)}</Address1>'
        f'<Address2>{esc(street)}</Address2>'
        f'<City>{esc(city)}</City>'
        f'<State>{esc(state)}</State>'
        f'<Zip5>{esc(zip_code[:5] if zip_code else "")}</Zip5>'
        f'<Zip4></Zip4>'
        f'</Address>'
        f'</AddressValidateRequest>'
    )
    return xml


async def validate_address(
    street: str, city: str, state: str, zip_code: str, street2: str = ""
) -> Tuple[bool, Dict]:
    """
    Validate an address using the USPS Web Tools API.
    
    Returns:
        (is_valid, result_dict)
        - If valid: (True, {"street": ..., "city": ..., "state": ..., "zip5": ..., "zip4": ..., ...})
        - If invalid: (False, {"error": "description"})
        - If API unavailable: (False, {"error": "USPS API unavailable", "skip": True})
    """
    if not USPS_USER_ID:
        logger.warning("USPS_USER_ID not configured — skipping address validation")
        return False, {"error": "USPS API not configured", "skip": True}
    
    if not street or not city or not state:
        return False, {"error": "Street, city, and state are required for address validation"}
    
    xml_payload = build_address_xml(street, city, state, zip_code, street2)
    
    try:
        async with aiohttp.ClientSession() as session:
            params = {
                "API": "Verify",
                "XML": xml_payload
            }
            async with session.get(USPS_API_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    logger.error(f"USPS API returned status {resp.status}")
                    return False, {"error": f"USPS API returned status {resp.status}", "skip": True}
                
                text = await resp.text()
                root = ET.fromstring(text)
                
                # Check for top-level error
                if root.tag == "Error":
                    desc = root.findtext("Description", "Unknown USPS error")
                    logger.error(f"USPS API error: {desc}")
                    return False, {"error": desc, "skip": True}
                
                addr = root.find("Address")
                if addr is None:
                    return False, {"error": "No address in USPS response", "skip": True}
                
                # Check for address-level error
                err = addr.find("Error")
                if err is not None:
                    desc = err.findtext("Description", "Address not found")
                    return False, {"error": desc}
                
                # Check for DPV confirmation
                dpv = addr.findtext("DPVConfirmation", "")
                # Y = confirmed, D = confirmed (missing secondary), S = confirmed (secondary not found)
                # N = not confirmed
                is_dpv_valid = dpv in ("Y", "D", "S")
                
                standardized = {
                    "street": addr.findtext("Address2", ""),
                    "street2": addr.findtext("Address1", ""),
                    "city": addr.findtext("City", ""),
                    "state": addr.findtext("State", ""),
                    "zip5": addr.findtext("Zip5", ""),
                    "zip4": addr.findtext("Zip4", ""),
                    "dpv_confirmed": dpv,
                    "footnotes": addr.findtext("Footnotes", ""),
                }
                
                if not is_dpv_valid:
                    standardized["warning"] = "Address found but delivery point not confirmed"
                
                return True, standardized
                
    except aiohttp.ClientError as e:
        logger.error(f"USPS API connection error: {e}")
        return False, {"error": f"Connection error: {str(e)}", "skip": True}
    except ET.ParseError as e:
        logger.error(f"USPS API XML parse error: {e}")
        return False, {"error": f"XML parse error: {str(e)}", "skip": True}
    except Exception as e:
        logger.error(f"USPS address validation unexpected error: {e}")
        return False, {"error": f"Unexpected error: {str(e)}", "skip": True}
