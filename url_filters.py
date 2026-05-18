from __future__ import annotations

import re

from extractor import extract_domain


SOCIAL_MEDIA_ROOTS = frozenset(
    {
        "facebook.com",
        "fb.com",
        "fb.me",
        "instagram.com",
        "twitter.com",
        "x.com",
        "t.co",
        "linkedin.com",
        "lnkd.in",
        "youtube.com",
        "youtu.be",
        "tiktok.com",
        "pinterest.com",
        "pin.it",
        "reddit.com",
        "redd.it",
        "tumblr.com",
        "snapchat.com",
        "threads.net",
        "vk.com",
        "weibo.com",
        "line.me",
        "telegram.org",
        "t.me",
        "whatsapp.com",
        "discord.com",
        "discord.gg",
        "vimeo.com",
        "dailymotion.com",
        "medium.com",
        "quora.com",
        "myspace.com",
    }
)

EXCLUDED_HTTP_STATUSES = frozenset({403, 404})
_HTTP_ERROR_RE = re.compile(r"HTTP\s+(\d{3})\b", re.IGNORECASE)


def is_social_media_domain(domain: str) -> bool:
    domain = domain.lower().strip().strip(".")
    if not domain:
        return False
    if domain in SOCIAL_MEDIA_ROOTS:
        return True
    return any(domain.endswith(f".{root}") for root in SOCIAL_MEDIA_ROOTS)


def is_social_media_url(url: str) -> bool:
    return is_social_media_domain(extract_domain(url))


def http_status_from_error(error: str) -> int | None:
    match = _HTTP_ERROR_RE.search(error or "")
    return int(match.group(1)) if match else None


def is_excluded_http_error(error: str) -> bool:
    status = http_status_from_error(error)
    return status in EXCLUDED_HTTP_STATUSES if status is not None else False


def should_skip_url_collection(url: str) -> str | None:
    if is_social_media_url(url):
        return "social media domain skipped"
    return None


def should_keep_crawl_result(result: dict[str, str]) -> bool:
    if is_social_media_domain(result.get("domain", "") or extract_domain(result.get("url", ""))):
        return False
    if result.get("status") == "failed" and is_excluded_http_error(result.get("error", "")):
        return False
    return True
