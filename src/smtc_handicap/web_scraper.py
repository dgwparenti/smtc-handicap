"""Scrape race result PDFs from the SMTC website (cresta-run.com)."""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup

from smtc_handicap.json_extractor import extract_race_data, has_ride_data, save_race_json
from smtc_handicap.pdf_generator import generate_results_pdf

logger = logging.getLogger(__name__)

BASE_URL = "https://www.cresta-run.com"
RATE_LIMIT_SECONDS = 0.5


def _get(url: str, timeout: int = 15) -> requests.Response:
    """GET with SSL-error retry (macOS cert issue)."""
    try:
        return requests.get(url, timeout=timeout)
    except requests.exceptions.SSLError:
        logger.debug("SSL verification failed for %s — retrying without verification", url)
        return requests.get(url, timeout=timeout, verify=False)


# ------------------------------------------------------------------
# Season page scraping
# ------------------------------------------------------------------


def scrape_season_events(season_slug: str) -> list[dict]:
    """Scrape all race/practice events from a season page.

    Args:
        season_slug: Season identifier, e.g. "2024-25".

    Returns:
        List of dicts with keys: title, date, category, url — sorted by date.
    """
    url = f"{BASE_URL}/season/{season_slug}"
    logger.info("Fetching season page: %s", url)

    resp = _get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    events: list[dict] = []
    for item in soup.select("div.ec-col-item.w-dyn-item"):
        category_el = item.select_one(".ec-category")
        category = category_el.get_text(strip=True).lower() if category_el else ""

        if category not in ("race", "practice"):
            continue

        title_el = item.select_one(".ec-title-backup")
        date_el = item.select_one(".ec-date")
        link_el = item.select_one("a.ec-link")

        if not link_el or not link_el.get("href"):
            continue

        events.append({
            "title": title_el.get_text(strip=True) if title_el else "",
            "date": date_el.get_text(strip=True) if date_el else "",
            "category": category,
            "url": link_el["href"],
        })

    events.sort(key=lambda e: e["date"])
    logger.info("Found %d race/practice events for season %s", len(events), season_slug)
    return events


# ------------------------------------------------------------------
# Event page scraping
# ------------------------------------------------------------------


def _fetch_event_page(event_path: str) -> tuple[str, BeautifulSoup]:
    """Fetch an event page, returning raw HTML text and parsed soup."""
    rel_path = event_path if event_path.startswith("/") else f"/{event_path.split('.com', 1)[-1]}"
    full_url = f"{BASE_URL}{rel_path}"
    resp = _get(full_url)
    resp.raise_for_status()
    return resp.text, BeautifulSoup(resp.text, "lxml")


def scrape_event_pdf_urls(
    event_path: str,
    _visited: set[str] | None = None,
    soup: BeautifulSoup | None = None,
) -> list[dict]:
    """Extract result PDF URLs from an event page.

    Args:
        event_path: Relative URL path, e.g. "/events-races/heaton-2025-01-04".
        _visited: Internal set tracking visited paths to prevent circular recursion.
        soup: Pre-parsed BeautifulSoup; if provided, skips the HTTP fetch.

    Returns:
        List of dicts with keys: url, label, source_page.
        May be empty if no result PDF is available.
    """
    if _visited is None:
        _visited = set()

    # Normalize to relative path for dedup
    rel_path = event_path if event_path.startswith("/") else f"/{event_path.split('.com', 1)[-1]}"
    if rel_path in _visited:
        return []
    _visited.add(rel_path)

    full_url = f"{BASE_URL}{rel_path}"

    if soup is None:
        _, soup = _fetch_event_page(event_path)

    pdfs: list[dict] = []

    # Primary: "Download Results" button
    for el in soup.select('.print-button-wrapper a[target="_blank"]'):
        href = el.get("href", "")
        label = el.get_text(strip=True).lower()
        if href.lower().endswith(".pdf") and "draw" not in label:
            pdfs.append({"url": href, "label": el.get_text(strip=True), "source_page": full_url})

    # Fallback: Tab 5 "View Results" link (only if no primary found)
    if not pdfs:
        for el in soup.select(".no-api-download-block a"):
            classes = el.get("class", [])
            href = el.get("href", "")
            label = el.get_text(strip=True).lower()
            if (
                href.lower().endswith(".pdf")
                and "w-condition-invisible" not in classes
                and "draw" not in label
            ):
                pdfs.append({
                    "url": href,
                    "label": el.get_text(strip=True),
                    "source_page": full_url,
                })

    # Check for child events (sub-events like Practice (T), Practice (J))
    for child in soup.select(".child-event .child-event--slug"):
        child_slug = child.get_text(strip=True)
        if child_slug:
            time.sleep(RATE_LIMIT_SECONDS)
            child_pdfs = scrape_event_pdf_urls(f"/events-races/{child_slug}", _visited)
            pdfs.extend(child_pdfs)

    return pdfs


# ------------------------------------------------------------------
# Filename handling
# ------------------------------------------------------------------


def _clean_cdn_filename(cdn_url: str) -> str:
    """Strip Webflow asset ID prefix and URL-decode the CDN filename."""
    url_path = urlparse(cdn_url).path
    encoded = url_path.split("/")[-1]
    decoded = unquote(encoded)

    # CDN format: {asset-id}_{original-filename}.pdf
    if "_" in decoded:
        return decoded.split("_", 1)[1]
    return decoded


def build_filename(event_date: str, event_url: str, cdn_url: str) -> str:
    """Build a local filename for a downloaded PDF.

    Tries to use the original CDN filename if it starts with YYYYMMDD.
    Falls back to constructing from event metadata.

    Args:
        event_date: Date string like "2025-01-04".
        event_url: Event page path like "/events-races/heaton-2025-01-04".
        cdn_url: Full CDN URL.

    Returns:
        Filename string like "20250104_rj_Heaton_Gold_Cup.pdf".
    """
    cdn_name = _clean_cdn_filename(cdn_url)

    # If CDN filename starts with YYYYMMDD, use it directly
    if len(cdn_name) >= 8 and cdn_name[:8].isdigit():
        return cdn_name

    # Construct from metadata
    date_compact = event_date.replace("-", "")
    slug = event_url.rstrip("/").split("/")[-1]
    return f"{date_compact}_{slug}.pdf"


# ------------------------------------------------------------------
# Download
# ------------------------------------------------------------------


def download_pdf(url: str, output_dir: Path, filename: str) -> Path | None:
    """Download a PDF from a CDN URL and save locally.

    Skips if file already exists. Validates PDF magic bytes.

    Returns:
        Path to saved file, or None if download failed.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename

    if output_path.exists():
        logger.debug("Already exists: %s", filename)
        return output_path

    try:
        resp = _get(url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("Download failed for %s: %s", filename, e)
        return None

    if resp.content[:5] != b"%PDF-":
        logger.warning("%s does not appear to be a PDF", filename)
        return None

    output_path.write_bytes(resp.content)
    logger.info("Downloaded: %s (%d bytes)", filename, len(resp.content))
    return output_path


# ------------------------------------------------------------------
# Log helpers
# ------------------------------------------------------------------


def _load_log(log_file: Path) -> list[dict]:
    if log_file.exists():
        return json.loads(log_file.read_text())
    return []


def _save_log(log_file: Path, log: list[dict]) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text(json.dumps(log, indent=2))


def _processed_urls(log: list[dict]) -> set[str]:
    """Return set of event URLs already processed successfully."""
    done_statuses = {"success", "json_extracted"}
    return {entry["event_url"] for entry in log if entry.get("status") in done_statuses}


# ------------------------------------------------------------------
# Orchestrator
# ------------------------------------------------------------------


def _build_event_slug(event_url: str, event_date: str) -> str:
    """Build a slug like '20211224_practice-2022-2687-12-24' from event metadata."""
    date_compact = event_date.replace("-", "")
    slug = event_url.rstrip("/").split("/")[-1]
    return f"{date_compact}_{slug}"


def scrape_and_download(
    seasons: list[str],
    output_dir: Path | str,
    log_file: Path | str,
    json_output_dir: Path | str | None = None,
) -> dict:
    """Scrape seasons and download all available result PDFs.

    For events without CDN PDFs, attempts to extract embedded JSON race data
    and generate archival PDFs.

    Args:
        seasons: List of season slugs, e.g. ["2024-25", "2023-24"].
        output_dir: Directory to save downloaded PDFs.
        log_file: Path to JSON log for idempotency tracking.
        json_output_dir: Directory to save extracted JSON files (optional).

    Returns:
        Summary dict with counts.
    """
    output_dir = Path(output_dir)
    log_file = Path(log_file)
    if json_output_dir is not None:
        json_output_dir = Path(json_output_dir)

    log = _load_log(log_file)
    done_urls = _processed_urls(log)

    summary = {
        "seasons_scraped": 0,
        "events_found": 0,
        "pdfs_downloaded": 0,
        "pdfs_skipped": 0,
        "pdfs_failed": 0,
        "pdfs_no_pdf": 0,
        "json_extracted": 0,
        "json_empty": 0,
        "pdfs_generated": 0,
    }

    for season in seasons:
        logger.info("=== Scraping season %s ===", season)
        events = scrape_season_events(season)
        summary["seasons_scraped"] += 1
        summary["events_found"] += len(events)
        time.sleep(RATE_LIMIT_SECONDS)

        for event in events:
            event_url = event["url"]

            if event_url in done_urls:
                logger.debug("Skipping already-processed: %s", event["title"])
                summary["pdfs_skipped"] += 1
                continue

            entry: dict = {
                "season": season,
                "event_title": event["title"],
                "event_date": event["date"],
                "event_category": event["category"],
                "event_url": event_url,
                "processed_at": datetime.now(UTC).isoformat(),
                "status": "failed",
            }

            try:
                time.sleep(RATE_LIMIT_SECONDS)
                html_text, soup = _fetch_event_page(event_url)

                pdfs = scrape_event_pdf_urls(event_url, soup=soup)

                if pdfs:
                    # CDN PDF path (existing logic)
                    pdf_info = pdfs[0]
                    filename = build_filename(event["date"], event_url, pdf_info["url"])
                    entry["pdf_url"] = pdf_info["url"]
                    entry["local_filename"] = filename

                    result = download_pdf(pdf_info["url"], output_dir, filename)

                    if result and result.exists():
                        entry["status"] = "success"
                        entry["local_path"] = str(result)
                        summary["pdfs_downloaded"] += 1
                        done_urls.add(event_url)
                    else:
                        entry["error"] = "Download failed or invalid PDF"
                        summary["pdfs_failed"] += 1
                else:
                    # JSON extraction fallback
                    race_data = extract_race_data(html_text)

                    if race_data and has_ride_data(race_data):
                        slug = _build_event_slug(event_url, event["date"])

                        # Save JSON
                        if json_output_dir is not None:
                            save_race_json(race_data, json_output_dir, f"{slug}.json")
                            entry["json_filename"] = f"{slug}.json"

                        # Generate PDF
                        pdf_path = output_dir / f"{slug}.pdf"
                        gen_result = generate_results_pdf(race_data, pdf_path)
                        if gen_result:
                            summary["pdfs_generated"] += 1
                            entry["local_path"] = str(gen_result)
                            entry["local_filename"] = f"{slug}.pdf"

                        entry["status"] = "json_extracted"
                        summary["json_extracted"] += 1
                        done_urls.add(event_url)

                    elif race_data:
                        entry["status"] = "empty_data"
                        entry["note"] = "Race JSON found but no ride data"
                        summary["json_empty"] += 1

                    else:
                        entry["status"] = "no_pdf"
                        entry["note"] = "No result PDF or embedded JSON found"
                        summary["pdfs_no_pdf"] += 1

            except Exception as e:
                logger.error("Error processing %s: %s", event["title"], e)
                entry["error"] = str(e)
                summary["pdfs_failed"] += 1

            log.append(entry)

        _save_log(log_file, log)

    logger.info("=" * 50)
    logger.info("Scrape complete:")
    for key, val in summary.items():
        logger.info("  %-18s %d", key, val)
    logger.info("=" * 50)

    return summary
