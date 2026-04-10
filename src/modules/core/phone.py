"""
Phone number OSINT via PhoneInfoga REST API.
PhoneInfoga runs as a sidecar service in Docker.

API base: /api
Routes:
  GET /api/numbers/:number/scan/local        -> number info (local library)
  GET /api/numbers/:number/scan/numverify    -> numverify data
  GET /api/numbers/:number/scan/googlesearch -> google dorks
  GET /api/numbers/:number/scan/ovh          -> OVH carrier data
"""

import aiohttp
import logging
import os

logger = logging.getLogger(__name__)

PHONEINFOGA_URL = os.getenv("PHONEINFOGA_URL", "http://localhost:5100")

SCANNERS = ("local", "numverify", "googlesearch", "ovh")


async def search_phone(phone: str) -> dict:
    """
    Search phone number using PhoneInfoga REST API.
    Returns structured result dict.
    """
    # Normalize: strip spaces/dashes/parens, keep digits and leading +
    number = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not number.startswith("+"):
        number = "+" + number
    # PhoneInfoga URL param uses the number without +
    num_param = number.lstrip("+")

    result = {
        "success": False,
        "query": phone,
        "type": "phone",
        "number_info": None,
        "scanners": [],
        "error": None,
    }

    try:
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            scan_results = []

            for scanner in SCANNERS:
                try:
                    async with session.get(
                        f"{PHONEINFOGA_URL}/api/numbers/{num_param}/scan/{scanner}"
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            payload = data.get("result") or {}

                            # local scanner gives us the main number info
                            if scanner == "local" and payload:
                                result["number_info"] = payload

                            # Only add scanner if it has non-empty values
                            if isinstance(payload, dict) and any(
                                v for v in payload.values() if v not in (None, "", False, 0, [])
                            ):
                                scan_results.append({
                                    "scanner": scanner,
                                    "data": payload,
                                })
                        else:
                            logger.debug(f"Scanner {scanner} returned {resp.status}")
                except Exception as e:
                    logger.debug(f"Scanner {scanner} failed: {e}")

            result["scanners"] = scan_results
            result["success"] = True

    except aiohttp.ClientConnectorError:
        result["error"] = "PhoneInfoga service unavailable. Check Docker setup."
    except Exception as e:
        logger.error(f"Phone search error: {e}", exc_info=True)
        result["error"] = str(e)

    return result
