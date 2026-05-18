from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable
from urllib.parse import urlparse

import aiohttp

from config import DEFAULT_USER_AGENT
from extractor import extract_domain, extract_emails, extract_phones, extract_title, html_to_text


SKIP_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".zip", ".rar", ".7z",
    ".mp4", ".mov", ".avi", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
)


@dataclass(frozen=True)
class CrawlConfig:
    workers: int = 40
    timeout_seconds: int = 10
    retry_count: int = 1
    delay_min: float = 0.2
    delay_max: float = 1.5
    user_agent: str = DEFAULT_USER_AGENT


ProgressCallback = Callable[[dict[str, str]], Awaitable[None] | None]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def should_skip_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "invalid URL"
    path = parsed.path.lower()
    if path.endswith(SKIP_EXTENSIONS):
        return "non-HTML file extension skipped"
    return None


def _empty_result(url: str, status: str, error: str) -> dict[str, str]:
    return {
        "url": url,
        "domain": extract_domain(url),
        "title": "",
        "emails": "",
        "phones": "",
        "status": status,
        "error": error,
        "crawled_at": now_iso(),
    }


async def crawl_one(session: aiohttp.ClientSession, url: str, config: CrawlConfig) -> dict[str, str]:
    skip_reason = should_skip_url(url)
    if skip_reason:
        return _empty_result(url, "skipped", skip_reason)

    last_error = ""
    for attempt in range(config.retry_count + 1):
        if config.delay_max > 0:
            await asyncio.sleep(random.uniform(max(0, config.delay_min), max(config.delay_min, config.delay_max)))
        try:
            async with session.get(url, allow_redirects=True) as response:
                content_type = response.headers.get("Content-Type", "").lower()
                if "html" not in content_type and "text/plain" not in content_type:
                    return _empty_result(url, "skipped", f"non-HTML content type: {content_type[:120]}")

                body = await response.text(errors="ignore")
                if response.status >= 400:
                    return _empty_result(str(response.url), "failed", f"HTTP {response.status}")

                text = html_to_text(body)
                return {
                    "url": str(response.url),
                    "domain": extract_domain(str(response.url)),
                    "title": extract_title(body),
                    "emails": ", ".join(extract_emails(text)),
                    "phones": ", ".join(extract_phones(text)),
                    "status": "success",
                    "error": "",
                    "crawled_at": now_iso(),
                }
        except asyncio.TimeoutError:
            last_error = "timeout"
        except aiohttp.ClientSSLError as exc:
            last_error = f"SSL error: {exc}"
        except aiohttp.ClientError as exc:
            last_error = f"client error: {exc}"
        except UnicodeError as exc:
            last_error = f"text decode error: {exc}"
        except Exception as exc:
            last_error = f"unexpected error: {exc}"

        if attempt < config.retry_count:
            await asyncio.sleep(min(2.0 * (attempt + 1), 5.0))

    return _empty_result(url, "failed", last_error or "unknown error")


async def crawl_urls(
    url_items: list[dict[str, str]],
    config: CrawlConfig,
    on_result: ProgressCallback | None = None,
) -> list[dict[str, str]]:
    queue: asyncio.Queue[dict[str, str] | None] = asyncio.Queue()
    for item in url_items:
        await queue.put(item)
    for _ in range(config.workers):
        await queue.put(None)

    timeout = aiohttp.ClientTimeout(total=config.timeout_seconds)
    connector = aiohttp.TCPConnector(limit=max(config.workers, 1), ttl_dns_cache=300, ssl=False)
    headers = {"User-Agent": config.user_agent, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
    results: list[dict[str, str]] = []

    async with aiohttp.ClientSession(timeout=timeout, connector=connector, headers=headers) as session:
        async def worker() -> None:
            while True:
                item = await queue.get()
                try:
                    if item is None:
                        return
                    result = await crawl_one(session, item["url"], config)
                    result["dork"] = item.get("dork", "")
                    results.append(result)
                    if on_result is not None:
                        maybe_awaitable = on_result(result)
                        if asyncio.iscoroutine(maybe_awaitable):
                            await maybe_awaitable
                finally:
                    queue.task_done()

        tasks = [asyncio.create_task(worker()) for _ in range(max(1, config.workers))]
        await queue.join()
        await asyncio.gather(*tasks, return_exceptions=True)

    return results
