"""
Phone number OSINT via PhoneInfoga REST API.
PhoneInfoga runs as a sidecar service in Docker.
"""

import asyncio
import aiohttp
import logging
import os

logger = logging.getLogger(__name__)

PHONEINFOGA_URL = os.getenv("PHONEINFOGA_URL", "http://localhost:5100")


async def search_phone(phone: str) -> dict:
    """
    Search phone number using PhoneInfoga REST API.
    Returns structured result dict.
    """
    # Normalize: strip spaces/dashes, ensure starts with +
    number = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not number.startswith("+"):
        number = "+" + number

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
            # 1. Validate & get number info
            async with session.post(
                f"{PHONEINFOGA_URL}/v2/numbers",
                json={"number": number.lstrip("+")},
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    result["error"] = f"PhoneInfoga error: {text}"
                    return result
                num_data = await resp.json()
                result["number_info"] = num_data

            # 2. Get available scanners
            async with session.get(f"{PHONEINFOGA_URL}/v2/scanners") as resp:
                scanners_data = await resp.json()
                scanner_names = [s["name"] for s in scanners_data.get("scanners", [])]

            # 3. Run each scanner
            scan_results = []
            for scanner_name in scanner_names:
                try:
                    async with session.post(
                        f"{PHONEINFOGA_URL}/v2/scanners/{scanner_name}/run",
                        json={"number": number.lstrip("+"), "options": {}},
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            scan_results.append({
                                "scanner": scanner_name,
                                "data": data,
                            })
                except Exception as e:
                    logger.debug(f"Scanner {scanner_name} failed: {e}")

            result["scanners"] = scan_results
            result["success"] = True

    except aiohttp.ClientConnectorError:
        result["error"] = "PhoneInfoga service unavailable. Check Docker setup."
    except Exception as e:
        logger.error(f"Phone search error: {e}", exc_info=True)
        result["error"] = str(e)

    return result
