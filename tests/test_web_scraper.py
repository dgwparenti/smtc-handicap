"""Unit tests for the web scraper module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import responses

from smtc_handicap.web_scraper import (
    build_filename,
    download_pdf,
    scrape_and_download,
    scrape_event_pdf_urls,
    scrape_season_events,
)

# ======================================================================
# HTML fixtures
# ======================================================================

SEASON_HTML = """
<html><body>
<div class="ec-col-item w-dyn-item" role="listitem">
  <div class="ec-title-backup">COMMITTEE MEETING 2025</div>
  <div class="ec-date">2024-11-07</div>
  <div class="ec-category">other</div>
  <a class="ec-link" href="/events-races/committee-meeting-2025-11-07">Link</a>
</div>
<div class="ec-col-item w-dyn-item" role="listitem">
  <div class="ec-title-backup">HEATON 2025</div>
  <div class="ec-date">2025-01-04</div>
  <div class="ec-category">race</div>
  <a class="ec-link" href="/events-races/heaton-2025-01-04">Link</a>
</div>
<div class="ec-col-item w-dyn-item" role="listitem">
  <div class="ec-title-backup">PRACTICE 2025 3220</div>
  <div class="ec-date">2024-12-22</div>
  <div class="ec-category">practice</div>
  <a class="ec-link" href="/events-races/practice-2025-3220-12-22">Link</a>
</div>
<div class="ec-col-item w-dyn-item" role="listitem">
  <div class="ec-title-backup">COCKTAILS 2025</div>
  <div class="ec-date">2025-01-10</div>
  <div class="ec-category">social</div>
  <a class="ec-link" href="/events-races/cocktails-2025-01-10">Link</a>
</div>
</body></html>
"""

EVENT_WITH_PDF_HTML = """
<html><body>
<div class="print-button-wrapper">
  <a href="https://cdn.prod.website-files.com/abc/def_20250104_rj_Heaton_Gold_Cup.pdf"
     target="_blank">Download Results</a>
  <a href="#">Print Results</a>
  <a href="https://cdn.prod.website-files.com/abc/ghi_20250104rj_Heaton_draw.pdf"
     target="_blank">Download Draw</a>
  <a href="#">Print Draw</a>
</div>
</body></html>
"""

EVENT_NO_PDF_HTML = """
<html><body>
<div class="print-button-wrapper">
  <a href="#">Print Results</a>
  <a href="#">Print Draw</a>
</div>
<div class="no-api-download-block">
  <a href="#" class="small-button light w-button w-condition-invisible">View Results</a>
  <a href="#" class="small-button light w-button w-condition-invisible">View Draw</a>
</div>
</body></html>
"""

EVENT_FALLBACK_PDF_HTML = """
<html><body>
<div class="print-button-wrapper">
  <a href="#">Print Results</a>
</div>
<div class="no-api-download-block">
  <a href="https://cdn.prod.website-files.com/abc/xyz_20250108_results.pdf"
     class="small-button light w-button">View Results</a>
  <a href="https://cdn.prod.website-files.com/abc/xyz_20250108_draw.pdf"
     class="small-button light w-button">View Draw</a>
</div>
</body></html>
"""


# ======================================================================
# TestScrapeSeasonEvents
# ======================================================================


class TestScrapeSeasonEvents:
    @responses.activate
    def test_filters_to_race_and_practice(self):
        responses.add(
            responses.GET,
            "https://www.cresta-run.com/season/2024-25",
            body=SEASON_HTML,
            status=200,
        )

        events = scrape_season_events("2024-25")

        assert len(events) == 2
        categories = {e["category"] for e in events}
        assert categories == {"race", "practice"}

    @responses.activate
    def test_sorted_by_date(self):
        responses.add(
            responses.GET,
            "https://www.cresta-run.com/season/2024-25",
            body=SEASON_HTML,
            status=200,
        )

        events = scrape_season_events("2024-25")

        dates = [e["date"] for e in events]
        assert dates == sorted(dates)

    @responses.activate
    def test_event_fields(self):
        responses.add(
            responses.GET,
            "https://www.cresta-run.com/season/2024-25",
            body=SEASON_HTML,
            status=200,
        )

        events = scrape_season_events("2024-25")

        race = next(e for e in events if e["category"] == "race")
        assert race["title"] == "HEATON 2025"
        assert race["date"] == "2025-01-04"
        assert race["url"] == "/events-races/heaton-2025-01-04"


# ======================================================================
# TestScrapeEventPdfUrls
# ======================================================================


class TestScrapeEventPdfUrls:
    @responses.activate
    def test_finds_results_pdf(self):
        responses.add(
            responses.GET,
            "https://www.cresta-run.com/events-races/heaton-2025-01-04",
            body=EVENT_WITH_PDF_HTML,
            status=200,
        )

        pdfs = scrape_event_pdf_urls("/events-races/heaton-2025-01-04")

        assert len(pdfs) == 1
        assert "Heaton_Gold_Cup" in pdfs[0]["url"]
        assert "draw" not in pdfs[0]["url"].lower()

    @responses.activate
    def test_no_pdf_available(self):
        responses.add(
            responses.GET,
            "https://www.cresta-run.com/events-races/old-race-2021",
            body=EVENT_NO_PDF_HTML,
            status=200,
        )

        pdfs = scrape_event_pdf_urls("/events-races/old-race-2021")

        assert len(pdfs) == 0

    @responses.activate
    def test_fallback_to_no_api_block(self):
        responses.add(
            responses.GET,
            "https://www.cresta-run.com/events-races/lightning-2025",
            body=EVENT_FALLBACK_PDF_HTML,
            status=200,
        )

        pdfs = scrape_event_pdf_urls("/events-races/lightning-2025")

        assert len(pdfs) == 1
        assert "results" in pdfs[0]["url"].lower()
        assert "draw" not in pdfs[0]["label"].lower()


# ======================================================================
# TestBuildFilename
# ======================================================================


class TestBuildFilename:
    def test_cdn_filename_with_date(self):
        cdn_url = "https://cdn.prod.website-files.com/abc/def_20250104_rj_Heaton_Gold_Cup.pdf"
        name = build_filename("2025-01-04", "/events-races/heaton-2025-01-04", cdn_url)
        assert name == "20250104_rj_Heaton_Gold_Cup.pdf"

    def test_cdn_filename_without_date(self):
        cdn_url = "https://cdn.prod.website-files.com/abc/def_results_some_race.pdf"
        name = build_filename("2025-01-04", "/events-races/heaton-2025-01-04", cdn_url)
        assert name == "20250104_heaton-2025-01-04.pdf"

    def test_cdn_filename_url_encoded(self):
        cdn_url = "https://cdn.prod.website-files.com/abc/def_20250104_rj%20Heaton.pdf"
        name = build_filename("2025-01-04", "/events-races/heaton-2025-01-04", cdn_url)
        assert name == "20250104_rj Heaton.pdf"


# ======================================================================
# TestDownloadPdf
# ======================================================================


class TestDownloadPdf:
    @responses.activate
    def test_valid_pdf(self, tmp_path):
        url = "https://cdn.prod.website-files.com/abc/def_20250104_results.pdf"
        pdf_content = b"%PDF-1.4 fake pdf content here"

        responses.add(responses.GET, url, body=pdf_content, status=200)

        result = download_pdf(url, tmp_path, "20250104_results.pdf")

        assert result is not None
        assert result.exists()
        assert result.name == "20250104_results.pdf"
        assert result.read_bytes() == pdf_content

    def test_skip_existing(self, tmp_path):
        existing = tmp_path / "20250104_results.pdf"
        existing.write_bytes(b"%PDF-1.4 already here")

        result = download_pdf("https://example.com/x.pdf", tmp_path, "20250104_results.pdf")

        assert result == existing

    @responses.activate
    def test_reject_non_pdf(self, tmp_path):
        url = "https://cdn.prod.website-files.com/abc/def_results.pdf"
        responses.add(responses.GET, url, body=b"<html>not a pdf</html>", status=200)

        result = download_pdf(url, tmp_path, "results.pdf")

        assert result is None

    @responses.activate
    def test_creates_output_dir(self, tmp_path):
        output_dir = tmp_path / "sub" / "dir"
        url = "https://cdn.prod.website-files.com/abc/def_results.pdf"
        responses.add(responses.GET, url, body=b"%PDF-1.4 content", status=200)

        result = download_pdf(url, output_dir, "results.pdf")

        assert result is not None
        assert output_dir.exists()


# ======================================================================
# TestScrapeAndDownload
# ======================================================================


class TestScrapeAndDownload:
    @responses.activate
    @patch("smtc_handicap.web_scraper.RATE_LIMIT_SECONDS", 0)
    def test_full_pipeline(self, tmp_path):
        pdf_content = b"%PDF-1.4 test content"
        cdn_url = "https://cdn.prod.website-files.com/abc/def_20250104_rj_Heaton.pdf"

        responses.add(
            responses.GET,
            "https://www.cresta-run.com/season/2024-25",
            body=SEASON_HTML,
            status=200,
        )
        # Practice event page — no PDF
        responses.add(
            responses.GET,
            "https://www.cresta-run.com/events-races/practice-2025-3220-12-22",
            body=EVENT_NO_PDF_HTML,
            status=200,
        )
        # Race event page — has PDF
        race_html = f"""
        <html><body>
        <div class="print-button-wrapper">
          <a href="{cdn_url}" target="_blank">Download Results</a>
        </div>
        </body></html>
        """
        responses.add(
            responses.GET,
            "https://www.cresta-run.com/events-races/heaton-2025-01-04",
            body=race_html,
            status=200,
        )
        # PDF download
        responses.add(responses.GET, cdn_url, body=pdf_content, status=200)

        log_file = tmp_path / "log.json"
        summary = scrape_and_download(
            ["2024-25"],
            output_dir=tmp_path / "pdfs",
            log_file=log_file,
        )

        assert summary["seasons_scraped"] == 1
        assert summary["events_found"] == 2
        assert summary["pdfs_downloaded"] == 1
        assert summary["pdfs_no_pdf"] == 1

        # Verify PDF was saved
        saved = list((tmp_path / "pdfs").glob("*.pdf"))
        assert len(saved) == 1
        assert saved[0].read_bytes() == pdf_content

        # Verify log was written
        log = json.loads(log_file.read_text())
        assert len(log) == 2

    @responses.activate
    @patch("smtc_handicap.web_scraper.RATE_LIMIT_SECONDS", 0)
    def test_idempotent_rerun(self, tmp_path):
        pdf_content = b"%PDF-1.4 test content"
        cdn_url = "https://cdn.prod.website-files.com/abc/def_20250104_rj_Heaton.pdf"

        # Pre-populate log with already-processed event
        log_file = tmp_path / "log.json"
        log_file.write_text(json.dumps([
            {
                "event_url": "/events-races/heaton-2025-01-04",
                "status": "success",
            }
        ]))

        responses.add(
            responses.GET,
            "https://www.cresta-run.com/season/2024-25",
            body=SEASON_HTML,
            status=200,
        )
        # Practice event — no PDF
        responses.add(
            responses.GET,
            "https://www.cresta-run.com/events-races/practice-2025-3220-12-22",
            body=EVENT_NO_PDF_HTML,
            status=200,
        )
        # Should NOT fetch the race page since it's already processed

        summary = scrape_and_download(
            ["2024-25"],
            output_dir=tmp_path / "pdfs",
            log_file=log_file,
        )

        assert summary["pdfs_skipped"] == 1
        assert summary["pdfs_downloaded"] == 0
