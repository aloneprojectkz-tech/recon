"""
Email enrichment: holehe + WHOIS/DNS (MX, SPF, DMARC, registration date).
"""

import asyncio
import logging
import sys
import os

logger = logging.getLogger(__name__)


# ── Holehe ────────────────────────────────────────────────────────────────────

async def run_holehe(email: str) -> list:
    """
    Run holehe against an email address.
    Returns list of dicts for found accounts.
    """
    results = []
    try:
        loop = asyncio.get_event_loop()
        out = await loop.run_in_executor(None, _run_holehe_sync, email)
        for item in (out or []):
            if item.get("exists"):
                results.append({
                    "name": item.get("name", ""),
                    "domain": item.get("domain", ""),
                    "exists": True,
                    "rateLimit": item.get("rateLimit", False),
                    "others": item.get("others"),
                })
    except ImportError:
        logger.warning("holehe not installed, skipping")
    except Exception as e:
        logger.error(f"holehe error: {e}", exc_info=True)
    return results


def _run_holehe_sync(email: str) -> list:
    """Sync wrapper to run holehe in a fresh event loop (called from executor)."""
    out = []
    try:
        import httpx
        from holehe.core import import_submodules, get_functions

        modules = import_submodules("holehe.modules")
        websites = get_functions(modules)

        async def _inner():
            sem = asyncio.Semaphore(15)
            async with httpx.AsyncClient(timeout=15) as client:
                async def run_one(site):
                    async with sem:
                        try:
                            await site(email, client, out)
                        except Exception:
                            pass
                await asyncio.gather(*[run_one(site) for site in websites])

        asyncio.run(_inner())
    except ImportError:
        logger.warning("holehe not installed")
    except Exception as e:
        logger.error(f"holehe sync error: {e}", exc_info=True)
    return out


# ── DNS / WHOIS enrichment ────────────────────────────────────────────────────

async def get_domain_info(email: str) -> dict:
    """
    Extract domain from email and run:
    - MX records
    - SPF record (TXT)
    - DMARC record
    - WHOIS registration date
    """
    domain = email.split("@")[-1].lower().strip()
    info = {
        "domain": domain,
        "mx_records": [],
        "spf": None,
        "dmarc": None,
        "whois": None,
        "error": None,
    }

    loop = asyncio.get_event_loop()

    # DNS lookups (run in executor to avoid blocking)
    try:
        dns_data = await loop.run_in_executor(None, _dns_lookup, domain)
        info.update(dns_data)
    except Exception as e:
        info["error"] = str(e)

    # WHOIS
    try:
        whois_data = await loop.run_in_executor(None, _whois_lookup, domain)
        info["whois"] = whois_data
    except Exception as e:
        logger.debug(f"WHOIS error for {domain}: {e}")

    return info


def _dns_lookup(domain: str) -> dict:
    """Synchronous DNS lookups using dnspython."""
    result = {"mx_records": [], "spf": None, "dmarc": None}
    try:
        import dns.resolver

        resolver = dns.resolver.Resolver()
        resolver.timeout = 5
        resolver.lifetime = 5

        # MX records
        try:
            mx_answers = resolver.resolve(domain, "MX")
            result["mx_records"] = sorted(
                [{"priority": r.preference, "host": str(r.exchange).rstrip(".")} for r in mx_answers],
                key=lambda x: x["priority"],
            )
        except Exception:
            pass

        # SPF (TXT records)
        try:
            txt_answers = resolver.resolve(domain, "TXT")
            for r in txt_answers:
                txt = b"".join(r.strings).decode("utf-8", errors="ignore")
                if txt.startswith("v=spf1"):
                    result["spf"] = txt
                    break
        except Exception:
            pass

        # DMARC
        try:
            dmarc_answers = resolver.resolve(f"_dmarc.{domain}", "TXT")
            for r in dmarc_answers:
                txt = b"".join(r.strings).decode("utf-8", errors="ignore")
                if "v=DMARC1" in txt:
                    result["dmarc"] = txt
                    break
        except Exception:
            pass

    except ImportError:
        logger.warning("dnspython not installed")

    return result


def _whois_lookup(domain: str) -> dict:
    """Synchronous WHOIS lookup."""
    try:
        import whois
        w = whois.whois(domain)
        creation = w.creation_date
        expiration = w.expiration_date
        updated = w.updated_date

        def _fmt(d):
            if isinstance(d, list):
                d = d[0]
            if d is None:
                return None
            return str(d)[:10]  # YYYY-MM-DD

        return {
            "registrar": w.registrar,
            "creation_date": _fmt(creation),
            "expiration_date": _fmt(expiration),
            "updated_date": _fmt(updated),
            "name_servers": w.name_servers if isinstance(w.name_servers, list) else [w.name_servers] if w.name_servers else [],
            "status": w.status if isinstance(w.status, list) else [w.status] if w.status else [],
        }
    except ImportError:
        logger.warning("python-whois not installed")
        return None
    except Exception as e:
        logger.debug(f"WHOIS failed: {e}")
        return None
