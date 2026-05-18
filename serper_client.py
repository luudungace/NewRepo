from __future__ import annotations

from typing import Any

import aiohttp

from config import SERPER_API_KEY


SERPER_ENDPOINT = "https://google.serper.dev/search"


class SerperError(RuntimeError):
    pass


async def search_dork(query: str, page: int, num: int, timeout_seconds: int = 20) -> list[dict[str, Any]]:
    if not SERPER_API_KEY:
        raise SerperError("Missing SERPER_API_KEY. Add it to .env before crawling.")
    if page < 1:
        raise ValueError("page must be >= 1")

    payload = {"q": query, "num": num, "page": page}
    headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(SERPER_ENDPOINT, json=payload, headers=headers) as response:
                text = await response.text()
                if response.status == 429:
                    raise SerperError("Serper rate limit reached (HTTP 429).")
                if response.status in {401, 403}:
                    raise SerperError("Serper authentication failed. Check SERPER_API_KEY.")
                if response.status >= 400:
                    raise SerperError(f"Serper API error HTTP {response.status}: {text[:300]}")
                try:
                    data = await response.json()
                except Exception as exc:
                    raise SerperError(f"Invalid Serper JSON response: {exc}") from exc
    except TimeoutError as exc:
        raise SerperError("Serper request timed out.") from exc
    except aiohttp.ClientError as exc:
        raise SerperError(f"Serper request failed: {exc}") from exc

    organic = data.get("organic")
    if organic is None:
        return []
    if not isinstance(organic, list):
        raise SerperError("Serper response field 'organic' is not a list.")

    results: list[dict[str, Any]] = []
    for item in organic:
        if not isinstance(item, dict):
            continue
        link = item.get("link")
        if not link:
            continue
        results.append(
            {
                "title": item.get("title", ""),
                "link": link,
                "snippet": item.get("snippet", ""),
                "position": item.get("position"),
            }
        )
    return results
