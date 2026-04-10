"""
Wrapper to run Blackbird OSINT searches from within the bot,
capturing output and returning structured results.
"""

import asyncio
import aiohttp
import json
import os
import sys
import time
import logging
from io import StringIO
from datetime import datetime

# Add blackbird src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from modules.core.phone import search_phone  # noqa: E402
from modules.core.email_enrichment import run_holehe, get_domain_info  # noqa: E402

logger = logging.getLogger(__name__)


class FakeConfig:
    """Minimal config object that mimics Blackbird's config module."""

    def __init__(self):
        # Paths
        self.LIST_DIRECTORY = "data"
        self.USERNAME_LIST_URL = (
            "https://raw.githubusercontent.com/WebBreacher/WhatsMyName/main/wmn-data.json"
        )
        self.USERNAME_LIST_FILENAME = "wmn-data.json"
        self.USERNAME_LIST_PATH = os.path.join(os.getcwd(), "data", "wmn-data.json")
        self.USERNAME_METADATA_LIST_PATH = os.path.join(os.getcwd(), "data", "wmn-metadata.json")
        self.EMAIL_LIST_PATH = os.path.join(os.getcwd(), "data", "email-data.json")
        self.LOG_PATH = os.path.join(os.getcwd(), "logs", "blackbird.log")

        # Search options
        self.username = None
        self.email = None
        self.username_file = None
        self.email_file = None
        self.permute = False
        self.permuteall = False
        self.csv = False
        self.pdf = False
        self.json = False
        self.filter = None
        self.no_nsfw = True  # Default: no NSFW in bot
        self.dump = False
        self.proxy = None
        self.verbose = False
        self.ai = False
        self.setup_ai = False
        self.timeout = 30
        self.max_concurrent_requests = 30
        self.no_update = True  # Don't auto-update in bot
        self.about = False
        self.instagram_session_id = os.getenv("INSTAGRAM_SESSION_ID")
        self.api_url = os.getenv("API_URL")

        # Runtime state
        self.usernameFoundAccounts = None
        self.emailFoundAccounts = None
        self.currentUser = None
        self.currentEmail = None
        self.username_sites = None
        self.email_sites = None
        self.metadata_params = None
        self.ai_analysis = None
        self.aiModel = None
        self.splash_line = ""

        self.dateRaw = datetime.now().strftime("%m_%d_%Y")
        self.datePretty = datetime.now().strftime("%B %d, %Y")
        self.saveDirectory = None

        # Silent console — we capture output ourselves
        from rich.console import Console
        self.console = Console(file=StringIO(), highlight=False)

        # User agent
        try:
            from modules.utils.userAgent import getRandomUserAgent
            self.userAgent = getRandomUserAgent(self)
        except Exception:
            self.userAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _ensure_data_dir():
    os.makedirs("data", exist_ok=True)
    os.makedirs("logs", exist_ok=True)


def _ensure_sites_list():
    """Download sites list if not present."""
    config = FakeConfig()
    wmn_path = config.USERNAME_LIST_PATH
    if not os.path.exists(wmn_path):
        logger.info("Downloading WhatsMyName list...")
        try:
            from modules.whatsmyname.list_operations import downloadList
            downloadList(config)
        except Exception as e:
            logger.error(f"Could not download sites list: {e}")


async def search_username(username: str, progress_callback=None) -> dict:
    """
    Search for a username across all sites.
    Returns dict with found accounts list.
    """
    _ensure_data_dir()
    _ensure_sites_list()

    config = FakeConfig()
    config.currentUser = username

    try:
        from modules.whatsmyname.list_operations import readList
        from modules.utils.filter import applyFilters, filterFoundAccounts
        from modules.utils.http_client import do_async_request
        from modules.utils.parse import extractMetadata, remove_duplicates

        data = readList("username", config)
        sitesToSearch = data["sites"]
        config.metadata_params = readList("metadata", config)
        config.username_sites = applyFilters(sitesToSearch, config)

        total = len(config.username_sites)
        completed = 0
        results = []

        async with aiohttp.ClientSession() as session:
            semaphore = asyncio.Semaphore(config.max_concurrent_requests)

            async def check_site(site):
                nonlocal completed
                url = site["uri_check"].replace("{account}", username)
                returnData = {
                    "name": site["name"],
                    "url": url,
                    "category": site["cat"],
                    "status": "NONE",
                    "metadata": None,
                }
                async with semaphore:
                    response = await do_async_request("GET", url, session, config)
                    if response is None:
                        returnData["status"] = "ERROR"
                        completed += 1
                        return returnData
                    try:
                        if (site["e_string"] in response["content"]) and (
                            site["e_code"] == response["status_code"]
                        ):
                            if (site["m_string"] not in response["content"]) and (
                                (site["m_code"] != response["status_code"])
                                if site["m_code"] != site["e_code"]
                                else True
                            ):
                                returnData["status"] = "FOUND"
                                try:
                                    if site["name"] in config.metadata_params.get("sites", {}):
                                        meta = extractMetadata(
                                            config.metadata_params["sites"][site["name"]],
                                            response,
                                            site["name"],
                                            config,
                                        )
                                        if meta:
                                            returnData["metadata"] = remove_duplicates(meta)
                                except Exception:
                                    pass
                            else:
                                returnData["status"] = "NOT-FOUND"
                        else:
                            returnData["status"] = "NOT-FOUND"
                    except Exception as e:
                        returnData["status"] = "ERROR"
                completed += 1
                if progress_callback and completed % 50 == 0:
                    await progress_callback(completed, total)
                return returnData

            tasks = [check_site(site) for site in config.username_sites]
            start_time = time.time()
            results = await asyncio.gather(*tasks)
            elapsed = round(time.time() - start_time, 1)

        found = [r for r in results if r["status"] == "FOUND"]
        return {
            "success": True,
            "query": username,
            "type": "username",
            "found": found,
            "total_checked": total,
            "elapsed": elapsed,
        }

    except Exception as e:
        logger.error(f"Username search error: {e}", exc_info=True)
        return {"success": False, "error": str(e), "query": username, "type": "username"}


async def search_email(email: str, progress_callback=None) -> dict:
    """
    Search for an email across all sites.
    Returns dict with found accounts list.
    """
    _ensure_data_dir()
    _ensure_sites_list()

    config = FakeConfig()
    config.currentEmail = email

    try:
        from modules.whatsmyname.list_operations import readList
        from modules.utils.filter import applyFilters, filterFoundAccounts
        from modules.utils.http_client import do_async_request
        from modules.utils.parse import extractMetadata
        from modules.utils.input import processInput

        data = readList("email", config)
        sitesToSearch = data["sites"]
        config.email_sites = applyFilters(sitesToSearch, config)

        total = len(config.email_sites)
        completed = 0
        results = []

        async with aiohttp.ClientSession() as session:
            semaphore = asyncio.Semaphore(config.max_concurrent_requests)

            async def check_site(site):
                nonlocal completed
                if site.get("input_operation"):
                    email_processed = processInput(email, site["input_operation"], config)
                else:
                    email_processed = email

                url = site["uri_check"].replace("{account}", email_processed)
                post_data = site["data"].replace("{account}", email_processed) if site.get("data") else None
                headers = site.get("headers")

                returnData = {
                    "name": site["name"],
                    "url": url,
                    "category": site["cat"],
                    "status": "NONE",
                    "metadata": None,
                }
                async with semaphore:
                    from modules.utils.precheck import perform_pre_check
                    if site.get("pre_check"):
                        headers = perform_pre_check(site["pre_check"], headers, config)
                        if headers is False:
                            returnData["status"] = "ERROR"
                            completed += 1
                            return returnData

                    response = await do_async_request(
                        site.get("method", "GET"), url, session, config, post_data, headers
                    )
                    if response is None:
                        returnData["status"] = "ERROR"
                        completed += 1
                        return returnData
                    try:
                        if (site["e_string"] in response["content"]) and (
                            site["e_code"] == response["status_code"]
                        ):
                            if (site["m_string"] not in response["content"]) and (
                                site["m_code"] != response["status_code"]
                            ):
                                returnData["status"] = "FOUND"
                                if site.get("metadata"):
                                    meta = extractMetadata(
                                        site["metadata"], response, site["name"], config
                                    )
                                    if meta:
                                        returnData["metadata"] = sorted(meta, key=lambda x: x["name"])
                            else:
                                returnData["status"] = "NOT-FOUND"
                        else:
                            returnData["status"] = "NOT-FOUND"
                    except Exception:
                        returnData["status"] = "ERROR"
                completed += 1
                if progress_callback and completed % 20 == 0:
                    await progress_callback(completed, total)
                return returnData

            tasks = [check_site(site) for site in config.email_sites]
            start_time = time.time()
            results = await asyncio.gather(*tasks)
            elapsed = round(time.time() - start_time, 1)

        found = [r for r in results if r["status"] == "FOUND"]
        return {
            "success": True,
            "query": email,
            "type": "email",
            "found": found,
            "total_checked": total,
            "elapsed": elapsed,
        }

    except Exception as e:
        logger.error(f"Email search error: {e}", exc_info=True)
        return {"success": False, "error": str(e), "query": email, "type": "email"}


async def search_email_full(email: str, progress_callback=None) -> dict:
    """
    Full email search: Blackbird (Recon) + holehe + DNS/WHOIS enrichment.
    Runs all three in parallel and merges results.
    """
    # Run all three concurrently
    blackbird_task = asyncio.create_task(search_email(email, progress_callback))
    holehe_task = asyncio.create_task(run_holehe(email))
    domain_task = asyncio.create_task(get_domain_info(email))

    blackbird_result, holehe_results, domain_info = await asyncio.gather(
        blackbird_task, holehe_task, domain_task, return_exceptions=True
    )

    # Handle exceptions from gather
    if isinstance(blackbird_result, Exception):
        blackbird_result = {"success": False, "error": str(blackbird_result), "found": [], "total_checked": 0, "elapsed": 0}
    if isinstance(holehe_results, Exception):
        holehe_results = []
    if isinstance(domain_info, Exception):
        domain_info = {"domain": email.split("@")[-1], "error": str(domain_info)}

    # Merge holehe results into found list
    found = list(blackbird_result.get("found", []))
    for h in (holehe_results or []):
        found.append({
            "name": h.get("name", h.get("domain", "?")),
            "url": f"https://{h.get('domain', '')}",
            "category": "holehe",
            "status": "FOUND",
            "metadata": [{"name": k, "value": str(v)} for k, v in (h.get("others") or {}).items()] if h.get("others") else None,
        })

    return {
        "success": blackbird_result.get("success", True),
        "query": email,
        "type": "email",
        "found": found,
        "total_checked": blackbird_result.get("total_checked", 0),
        "elapsed": blackbird_result.get("elapsed", 0),
        "holehe_count": len(holehe_results or []),
        "domain_info": domain_info,
        "error": blackbird_result.get("error"),
    }
