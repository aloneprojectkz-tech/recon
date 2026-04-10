"""
Phone number OSINT:
  1. NumVerify API  — valid, type, country, carrier
  2. PhoneInfoga    — local/ovh/googlesearch scanners
  3. Platform check — проверка регистрации номера на платформах (Microsoft и др.)
"""

import aiohttp
import asyncio
import logging
import os

logger = logging.getLogger(__name__)

PHONEINFOGA_URL = os.getenv("PHONEINFOGA_URL", "http://localhost:5100")
NUMVERIFY_KEY   = os.getenv("NUMVERIFY_API_KEY", "")

# NumVerify бесплатный план требует http (не https)
NUMVERIFY_URL = "http://apilayer.net/api/validate"

# Платформы для проверки по номеру телефона
PLATFORM_CHECKS = [
    {
        "name": "microsoft",
        "url": "https://login.live.com/GetCredentialType.srf",
        "method": "POST",
        "json": {"username": "{number}"},
        "found_key": "IfExistsResult",
        "found_value": 0,
    },
]


async def search_phone(phone: str) -> dict:
    """
    Full phone OSINT: NumVerify + PhoneInfoga + platform checks.
    """
    number = _normalize(phone)
    num_param = number.lstrip("+")

    result = {
        "success": False,
        "query": phone,
        "type": "phone",
        "number_info": None,
        "scanners": [],
        "registered_platforms": [],
        "error": None,
    }

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:

        # ── 1. NumVerify ──────────────────────────────────────────────────────
        numverify_data = await _numverify(session, num_param)
        if numverify_data:
            result["number_info"] = numverify_data
            result["success"] = True

        # ── 2. PhoneInfoga scanners ───────────────────────────────────────────
        pif_tasks = [
            _phoneinfoga_scan(session, num_param, scanner)
            for scanner in ("local", "ovh", "googlesearch")
        ]
        pif_results = await asyncio.gather(*pif_tasks, return_exceptions=True)

        for r in pif_results:
            if isinstance(r, dict) and r.get("data"):
                result["scanners"].append(r)
                result["success"] = True
                # Merge local scan into number_info if numverify failed
                if r["scanner"] == "local" and not result["number_info"]:
                    result["number_info"] = r["data"]

        # ── 3. Platform checks ────────────────────────────────────────────────
        platform_tasks = [
            _check_platform(session, number, p) for p in PLATFORM_CHECKS
        ]
        platform_results = await asyncio.gather(*platform_tasks, return_exceptions=True)
        result["registered_platforms"] = [
            p for p in platform_results if isinstance(p, str)
        ]

    return result


async def _numverify(session: aiohttp.ClientSession, number: str) -> dict | None:
    """Call NumVerify API."""
    if not NUMVERIFY_KEY:
        return None
    try:
        async with session.get(
            NUMVERIFY_URL,
            params={"access_key": NUMVERIFY_KEY, "number": number, "format": 1},
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None)
            if not data.get("valid") and data.get("error"):
                logger.warning(f"NumVerify error: {data['error']}")
                return None
            return {
                "valid":        data.get("valid", False),
                "number":       data.get("number", number),
                "local_format": data.get("local_format", ""),
                "international_format": data.get("international_format", ""),
                "country_prefix": data.get("country_prefix", ""),
                "country_code":   data.get("country_code", ""),
                "country_name":   data.get("country_name", ""),
                "location":       data.get("location", ""),
                "carrier":        data.get("carrier", ""),
                "line_type":      data.get("line_type", ""),
            }
    except Exception as e:
        logger.debug(f"NumVerify failed: {e}")
        return None


async def _phoneinfoga_scan(session: aiohttp.ClientSession, number: str, scanner: str) -> dict:
    """Run a single PhoneInfoga scanner."""
    try:
        async with session.get(
            f"{PHONEINFOGA_URL}/api/numbers/{number}/scan/{scanner}"
        ) as resp:
            if resp.status != 200:
                return {}
            data = await resp.json()
            payload = data.get("result") or {}
            if not isinstance(payload, dict):
                return {}
            # Filter empty values
            clean = {k: v for k, v in payload.items() if v not in (None, "", False, 0, [], {})}
            if not clean:
                return {}
            return {"scanner": scanner, "data": clean}
    except Exception as e:
        logger.debug(f"PhoneInfoga {scanner} failed: {e}")
        return {}


async def _check_platform(session: aiohttp.ClientSession, number: str, platform: dict) -> str | None:
    """Check if a phone number is registered on a platform."""
    try:
        url = platform["url"]
        body = {k: v.replace("{number}", number) if isinstance(v, str) else v
                for k, v in platform["json"].items()}
        async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                if data.get(platform["found_key"]) == platform["found_value"]:
                    return platform["name"]
    except Exception as e:
        logger.debug(f"Platform check {platform['name']} failed: {e}")
    return None


def _normalize(phone: str) -> str:
    """Normalize phone number to E.164 format."""
    n = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not n.startswith("+"):
        n = "+" + n
    return n
