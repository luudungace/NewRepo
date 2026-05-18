from __future__ import annotations

import re
from urllib.parse import urlparse

import phonenumbers
import tldextract
from bs4 import BeautifulSoup


EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w-])", re.IGNORECASE)
VN_PHONE_RE = re.compile(r"(?:(?:\+?84|0)[\s.\-()]*)?(?:\d[\s.\-()]*){8,11}")


def extract_title(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    if soup.title and soup.title.string:
        return " ".join(soup.title.string.split())[:500]
    h1 = soup.find("h1")
    return " ".join(h1.get_text(" ", strip=True).split())[:500] if h1 else ""


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)


def extract_emails(text: str) -> list[str]:
    emails = {match.group(0).strip().lower().strip(".,;:") for match in EMAIL_RE.finditer(text)}
    return sorted(email for email in emails if ".." not in email)


def _normalize_candidate(candidate: str) -> str:
    candidate = candidate.strip()
    candidate = re.sub(r"[^\d+]", "", candidate)
    if candidate.startswith("84") and not candidate.startswith("+84"):
        candidate = "+" + candidate
    return candidate


def extract_phones(text: str, region: str = "VN") -> list[str]:
    found: set[str] = set()

    for match in VN_PHONE_RE.finditer(text):
        normalized = _normalize_candidate(match.group(0))
        digits = re.sub(r"\D", "", normalized)
        if normalized.startswith("+84") or normalized.startswith("0"):
            if 9 <= len(digits) <= 12:
                found.add(normalized)

    for match in phonenumbers.PhoneNumberMatcher(text, region):
        if phonenumbers.is_possible_number(match.number):
            found.add(phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164))

    return sorted(found)


def extract_domain(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"http://{url}")
    host = (parsed.hostname or "").lower().strip(".")
    extracted = tldextract.extract(host)
    if extracted.domain and extracted.suffix:
        return f"{extracted.domain}.{extracted.suffix}"
    return host
