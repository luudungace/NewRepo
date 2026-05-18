from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

from config import SERPER_API_KEY
from crawler import CrawlConfig, crawl_urls
from db import (
    add_log,
    count_results,
    create_job,
    get_job,
    get_logs,
    get_results,
    init_db,
    insert_dork,
    list_jobs,
    update_dork_status,
    update_job_progress,
    upsert_result,
)
from export_utils import export_results_to_excel
from extractor import extract_domain
from serper_client import SerperError, search_dork
from sheets_sync import push_results_to_sheet


st.set_page_config(page_title="LinkIntel Phase 1", layout="wide")
init_db()


def parse_dorks(raw: str) -> list[str]:
    return [line.strip() for line in raw.splitlines() if line.strip()]


def normalize_url(url: str) -> str:
    return url.strip().rstrip("/")


async def collect_serper_urls(
    job_id: int,
    dorks: list[str],
    max_pages_per_dork: int,
    results_per_page: int,
    max_urls_total: int,
    dedupe_mode: str,
) -> list[dict[str, str]]:
    seen: set[str] = set()
    items: list[dict[str, str]] = []

    for dork in dorks:
        update_dork_status(job_id, dork, "running")
        add_log(job_id, f"Searching Serper for dork: {dork}")
        for page in range(1, max_pages_per_dork + 1):
            if len(items) >= max_urls_total:
                break
            try:
                organic = await search_dork(dork, page=page, num=results_per_page)
            except SerperError as exc:
                add_log(job_id, f"Serper error for '{dork}' page {page}: {exc}", "ERROR")
                update_dork_status(job_id, dork, "failed")
                break
            except Exception as exc:
                add_log(job_id, f"Unexpected Serper error for '{dork}' page {page}: {exc}", "ERROR")
                update_dork_status(job_id, dork, "failed")
                break

            add_log(job_id, f"Serper returned {len(organic)} organic results for page {page}: {dork}")
            if not organic:
                break

            for result in organic:
                url = normalize_url(str(result.get("link", "")))
                if not url:
                    continue
                key = extract_domain(url) if dedupe_mode == "domain" else url.lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                items.append({"url": url, "dork": dork})
                if len(items) >= max_urls_total:
                    break
        else:
            update_dork_status(job_id, dork, "done")
            continue
        if len(items) >= max_urls_total:
            update_dork_status(job_id, dork, "limited")

    update_job_progress(job_id, total_urls=len(items), status="crawling")
    add_log(job_id, f"Collected {len(items)} unique URLs after dedupe mode '{dedupe_mode}'.")
    return items


async def run_job(
    job_id: int,
    dorks: list[str],
    config: CrawlConfig,
    max_pages_per_dork: int,
    results_per_page: int,
    max_urls_total: int,
    dedupe_mode: str,
    progress_box: Any,
    logs_box: Any,
) -> None:
    update_job_progress(job_id, status="searching")
    add_log(job_id, "Job started.")
    items = await collect_serper_urls(
        job_id,
        dorks,
        max_pages_per_dork=max_pages_per_dork,
        results_per_page=results_per_page,
        max_urls_total=max_urls_total,
        dedupe_mode=dedupe_mode,
    )
    if not items:
        update_job_progress(job_id, status="failed")
        add_log(job_id, "No URLs to crawl.", "ERROR")
        return

    stats = {"crawled": 0, "success": 0, "failed": 0}

    def on_result(result: dict[str, str]) -> None:
        stats["crawled"] += 1
        if result["status"] == "success":
            stats["success"] += 1
        elif result["status"] in {"failed", "skipped"}:
            stats["failed"] += 1

        upsert_result(
            job_id=job_id,
            dork=result.get("dork", ""),
            url=result["url"],
            domain=result["domain"],
            title=result["title"],
            emails=result["emails"],
            phones=result["phones"],
            status=result["status"],
            error=result["error"],
            crawled_at=result["crawled_at"],
        )
        update_job_progress(
            job_id,
            crawled_urls=stats["crawled"],
            success_count=stats["success"],
            failed_count=stats["failed"],
        )
        if result["status"] == "success":
            add_log(job_id, f"Crawled OK: {result['url']}")
        else:
            add_log(job_id, f"{result['status'].upper()}: {result['url']} - {result['error']}", "WARNING")
        render_progress(job_id, progress_box)
        render_logs(job_id, logs_box)

    await crawl_urls(items, config, on_result=on_result)
    update_job_progress(job_id, status="done")
    add_log(job_id, "Job completed.")


def render_progress(job_id: int, container: Any) -> None:
    job = get_job(job_id) or {}
    cols = container.columns(4)
    cols[0].metric("URL từ Serper", job.get("total_urls", 0))
    cols[1].metric("Đã crawl", job.get("crawled_urls", 0))
    cols[2].metric("Success", job.get("success_count", 0))
    cols[3].metric("Failed/Skipped", job.get("failed_count", 0))


def render_logs(job_id: int, container: Any, limit: int = 80) -> None:
    logs = get_logs(job_id, limit=limit)
    lines = [f"[{log['created_at']}] {log['level']}: {log['message']}" for log in reversed(logs)]
    container.code("\n".join(lines) if lines else "No logs yet.", language="text")


def render_results(job_id: int | None) -> None:
    st.subheader("Results")
    col_a, col_b, col_c, col_d = st.columns([3, 1, 1, 1])
    search = col_a.text_input("Search domain, email, phone, status, URL, title", value="")
    status = col_b.selectbox("Status", ["all", "success", "failed", "skipped"])
    page_size = col_c.number_input("Rows/page", min_value=10, max_value=500, value=100, step=10)
    total = count_results(job_id=job_id, search=search, status=status)
    max_page = max(1, (total + int(page_size) - 1) // int(page_size))
    page = col_d.number_input("Page", min_value=1, max_value=max_page, value=1, step=1)
    offset = (int(page) - 1) * int(page_size)

    rows = get_results(job_id=job_id, search=search, status=status, limit=int(page_size), offset=offset)
    st.caption(f"{total} rows total")
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


st.title("LinkIntel Phase 1 - SERP Harvester")

jobs = list_jobs()
job_options = {"All jobs": None}
for job in jobs:
    job_options[f"#{job['id']} - {job['name']} ({job['status']})"] = int(job["id"])

selected_label = st.sidebar.selectbox("View job", list(job_options.keys()))
selected_job_id = job_options[selected_label]

with st.sidebar:
    st.header("Run Config")
    max_pages_per_dork = st.number_input("max_pages_per_dork", min_value=1, max_value=100, value=10)
    results_per_page = st.number_input("results_per_page", min_value=1, max_value=100, value=10)
    max_urls_total = st.number_input("max_urls_total", min_value=1, max_value=100_000, value=2000)
    workers = st.number_input("workers", min_value=1, max_value=300, value=40)
    timeout_seconds = st.number_input("timeout_seconds", min_value=1, max_value=120, value=10)
    retry_count = st.number_input("retry_count", min_value=0, max_value=5, value=1)
    delay_min = st.number_input("delay_min", min_value=0.0, max_value=60.0, value=0.2, step=0.1)
    delay_max = st.number_input("delay_max", min_value=0.0, max_value=60.0, value=1.5, step=0.1)
    dedupe_mode = st.selectbox("dedupe_mode", ["url", "domain"])

dorks_raw = st.text_area("Google Dorks (one per line, max 10)", height=180)
dorks = parse_dorks(dorks_raw)
if len(dorks) > 10:
    st.error("Tối đa 10 dorks/lần. Hãy giảm số dòng trước khi chạy.")
if not SERPER_API_KEY:
    st.warning("Thiếu SERPER_API_KEY trong .env. Crawl sẽ không chạy cho đến khi cấu hình key.")

start = st.button("Start Crawl", type="primary", disabled=not dorks or len(dorks) > 10 or not SERPER_API_KEY)

progress_box = st.container()
logs_box = st.empty()

if start:
    job_name = f"LinkIntel {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    job_id = create_job(job_name)
    for dork in dorks:
        insert_dork(job_id, dork)
    st.session_state["active_job_id"] = job_id
    selected_job_id = job_id

    crawl_config = CrawlConfig(
        workers=int(workers),
        timeout_seconds=int(timeout_seconds),
        retry_count=int(retry_count),
        delay_min=float(delay_min),
        delay_max=float(delay_max),
    )
    with st.spinner("Crawling..."):
        try:
            asyncio.run(
                run_job(
                    job_id,
                    dorks,
                    crawl_config,
                    int(max_pages_per_dork),
                    int(results_per_page),
                    int(max_urls_total),
                    dedupe_mode,
                    progress_box,
                    logs_box,
                )
            )
        except Exception as exc:
            update_job_progress(job_id, status="failed")
            add_log(job_id, f"Fatal job error: {exc}", "ERROR")
            st.error(f"Job failed: {exc}")
    st.success(f"Job #{job_id} finished.")

if selected_job_id:
    render_progress(selected_job_id, progress_box)
    render_logs(selected_job_id, logs_box)

render_results(selected_job_id)

st.subheader("Export / Google Sheets")
if selected_job_id is None:
    st.info("Select a specific job in the sidebar to export or push to Google Sheet.")
else:
    export_col, sheet_col = st.columns(2)
    with export_col:
        if st.button("Export Excel"):
            try:
                filepath = export_results_to_excel(selected_job_id)
                st.success(f"Exported: {filepath}")
            except Exception as exc:
                st.error(f"Export failed: {exc}")

    with sheet_col:
        with st.form("sheet_form"):
            spreadsheet_id = st.text_input("Google Sheet ID")
            worksheet_name = st.text_input("Worksheet name", value=f"job_{selected_job_id}")
            submitted = st.form_submit_button("Push to Google Sheet")
        if submitted:
            try:
                count = push_results_to_sheet(selected_job_id, spreadsheet_id, worksheet_name)
                st.success(f"Pushed {count} rows to Google Sheet.")
            except Exception as exc:
                add_log(selected_job_id, f"Google Sheet push failed: {exc}", "ERROR")
                st.error(f"Google Sheet push failed: {exc}")
