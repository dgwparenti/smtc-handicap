"""Functional tests for GmailExtractor — no Gmail API access needed."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import patch

import requests
import responses

from smtc_handicap.gmail_extractor import GmailExtractor

# ======================================================================
# TestExtractResultsLink
# ======================================================================


class TestExtractResultsLink:
    def test_mailchimp_link(self, email_mailchimp):
        link = GmailExtractor.extract_results_link(email_mailchimp)
        assert link is not None
        assert "list-manage.com/track/click" in link
        assert "abc123" in link

    def test_direct_cdn_link(self, email_direct_cdn):
        link = GmailExtractor.extract_results_link(email_direct_cdn)
        assert link is not None
        assert "cdn.prod.website-files.com" in link
        assert link.endswith(".pdf")

    def test_skip_draw_only(self, email_draw_only):
        link = GmailExtractor.extract_results_link(email_draw_only)
        assert link is None

    def test_no_link(self, email_no_link):
        link = GmailExtractor.extract_results_link(email_no_link)
        assert link is None

    def test_both_results_and_draw(self, email_both):
        link = GmailExtractor.extract_results_link(email_both)
        assert link is not None
        assert "draw" not in link.lower()
        # Should pick the results PDF, not the draw
        assert "20260120" in link

    def test_case_insensitive_results_text(self):
        html = """
        <html><body>
        <p>For Today's Results please
          <a href="https://cresta-run.us18.list-manage.com/track/click?u=x&id=y">Click Here</a>
        </p>
        </body></html>
        """
        link = GmailExtractor.extract_results_link(html)
        assert link is not None

    def test_encoded_cdn_url(self):
        html = """
        <html><body>
        <p>For today's results please
          <a href="https://cdn.prod.website-files.com/abc/def_20260123%20pt%20%2B%20pj.pdf">here</a>
        </p>
        </body></html>
        """
        link = GmailExtractor.extract_results_link(html)
        assert link is not None
        assert link.endswith(".pdf")


# ======================================================================
# TestResolvePdfUrl
# ======================================================================


class TestResolvePdfUrl:
    def test_cdn_passthrough(self):
        cdn_url = "https://cdn.prod.website-files.com/abc/def_20260123%20pt.pdf"
        assert GmailExtractor.resolve_pdf_url(cdn_url) == cdn_url

    @responses.activate
    def test_mailchimp_redirect(self):
        mailchimp_url = "https://cresta-run.us18.list-manage.com/track/click?u=x&id=y"
        cdn_url = "https://cdn.prod.website-files.com/abc/def_20260123%20pt.pdf"

        responses.add(
            responses.HEAD,
            mailchimp_url,
            status=200,
            headers={"Location": cdn_url},
        )
        # responses library follows redirects and returns the final URL
        # We need to simulate the redirect properly
        responses.reset()
        responses.add(
            responses.HEAD,
            mailchimp_url,
            status=302,
            headers={"Location": cdn_url},
        )
        responses.add(
            responses.HEAD,
            cdn_url,
            status=200,
        )

        result = GmailExtractor.resolve_pdf_url(mailchimp_url)
        assert result == cdn_url

    @patch("smtc_handicap.gmail_extractor.requests.head")
    def test_ssl_error_fallback(self, mock_head):
        """SSL failure on first attempt retries with verify=False."""
        mailchimp_url = "https://cresta-run.us18.list-manage.com/track/click?u=abc"
        cdn_url = "https://cdn.prod.website-files.com/results.pdf"

        ssl_error = requests.exceptions.SSLError("certificate verify failed")
        ok_response = requests.models.Response()
        ok_response.status_code = 200
        ok_response.url = cdn_url

        mock_head.side_effect = [ssl_error, ok_response]

        result = GmailExtractor.resolve_pdf_url(mailchimp_url)

        assert result == cdn_url
        assert mock_head.call_count == 2
        first_call = mock_head.call_args_list[0]
        second_call = mock_head.call_args_list[1]
        assert first_call.kwargs.get("verify", True) is not False
        assert second_call.kwargs.get("verify") is False


# ======================================================================
# TestCleanFilename
# ======================================================================


class TestCleanFilename:
    def test_strip_prefix(self):
        url = "https://cdn.prod.website-files.com/6683aa/69736fc8a00653a090a5668e_20260123%20pt%20%2B%20pj%20%2B%20splits.pdf"
        name = GmailExtractor.clean_filename(url)
        assert name == "20260123 pt + pj + splits.pdf"

    def test_no_prefix(self):
        url = "https://cdn.prod.website-files.com/6683aa/20260123%20rt.pdf"
        name = GmailExtractor.clean_filename(url)
        assert name == "20260123 rt.pdf"

    def test_url_decoding(self):
        url = "https://cdn.prod.website-files.com/x/abc_20260215%20rt%20%2B%20rj.pdf"
        name = GmailExtractor.clean_filename(url)
        assert name == "20260215 rt + rj.pdf"


# ======================================================================
# TestParsePdfFilename
# ======================================================================


class TestParsePdfFilename:
    def test_practice_only(self):
        result = GmailExtractor.parse_pdf_filename("20260123 pt + pj.pdf")
        assert result["date"] == "20260123"
        assert result["events"] == ["pt", "pj"]
        assert result["has_splits"] is False

    def test_race_top_with_name(self):
        result = GmailExtractor.parse_pdf_filename("20260120 rt + rj.pdf")
        assert result["date"] == "20260120"
        assert result["events"] == ["rt", "rj"]
        assert result["has_splits"] is False

    def test_race_junction(self):
        result = GmailExtractor.parse_pdf_filename("20260118 rj.pdf")
        assert result["date"] == "20260118"
        assert result["events"] == ["rj"]

    def test_multi_event(self):
        result = GmailExtractor.parse_pdf_filename("20260115 rt + rj + pt + pj.pdf")
        assert result["date"] == "20260115"
        assert len(result["events"]) == 4

    def test_splits_flag(self):
        result = GmailExtractor.parse_pdf_filename("20260123 pt + pj + splits.pdf")
        assert result["has_splits"] is True
        assert "splits" not in result["events"]

    def test_no_splits(self):
        result = GmailExtractor.parse_pdf_filename("20260123 rt.pdf")
        assert result["has_splits"] is False


# ======================================================================
# TestExtractHtmlFromPayload
# ======================================================================


class TestExtractHtmlFromPayload:
    def test_simple_html(self):
        payload = {
            "mimeType": "text/html",
            "body": {"data": base64.urlsafe_b64encode(b"<html>hello</html>").decode()},
        }
        result = GmailExtractor._extract_html_from_payload(payload)
        assert result == "<html>hello</html>"

    def test_multipart_alternative(self):
        html_data = base64.urlsafe_b64encode(b"<html>content</html>").decode()
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": base64.urlsafe_b64encode(b"plain text").decode()},
                },
                {
                    "mimeType": "text/html",
                    "body": {"data": html_data},
                },
            ],
        }
        result = GmailExtractor._extract_html_from_payload(payload)
        assert result == "<html>content</html>"

    def test_nested_multipart(self):
        html_data = base64.urlsafe_b64encode(b"<html>nested</html>").decode()
        payload = {
            "mimeType": "multipart/mixed",
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "body": {"data": base64.urlsafe_b64encode(b"plain").decode()},
                        },
                        {
                            "mimeType": "text/html",
                            "body": {"data": html_data},
                        },
                    ],
                },
            ],
        }
        result = GmailExtractor._extract_html_from_payload(payload)
        assert result == "<html>nested</html>"

    def test_no_html_part(self):
        payload = {
            "mimeType": "text/plain",
            "body": {"data": base64.urlsafe_b64encode(b"just text").decode()},
        }
        result = GmailExtractor._extract_html_from_payload(payload)
        assert result is None


# ======================================================================
# TestDownloadPdf
# ======================================================================


class TestDownloadPdf:
    @responses.activate
    def test_valid_pdf(self, tmp_path):
        pdf_url = "https://cdn.prod.website-files.com/x/abc_20260123%20pt.pdf"
        pdf_content = b"%PDF-1.4 fake pdf content here"

        responses.add(responses.GET, pdf_url, body=pdf_content, status=200)

        extractor = _make_extractor(tmp_path)
        result = extractor.download_pdf(pdf_url)

        assert result is not None
        assert result.exists()
        assert result.name == "20260123 pt.pdf"
        assert result.read_bytes() == pdf_content

    def test_skip_existing(self, tmp_path):
        pdf_url = "https://cdn.prod.website-files.com/x/abc_20260123%20pt.pdf"
        existing = tmp_path / "20260123 pt.pdf"
        existing.write_bytes(b"%PDF-1.4 already here")

        extractor = _make_extractor(tmp_path)
        result = extractor.download_pdf(pdf_url)

        assert result == existing

    @responses.activate
    def test_reject_non_pdf(self, tmp_path):
        pdf_url = "https://cdn.prod.website-files.com/x/abc_20260123%20pt.pdf"
        responses.add(
            responses.GET,
            pdf_url,
            body=b"<html>not a pdf</html>",
            status=200,
        )

        extractor = _make_extractor(tmp_path)
        result = extractor.download_pdf(pdf_url)

        assert result is None

    @responses.activate
    def test_creates_output_dir(self, tmp_path):
        output_dir = tmp_path / "sub" / "dir"
        pdf_url = "https://cdn.prod.website-files.com/x/abc_20260123%20pt.pdf"
        pdf_content = b"%PDF-1.4 fake pdf content"

        responses.add(responses.GET, pdf_url, body=pdf_content, status=200)

        extractor = _make_extractor(output_dir)
        result = extractor.download_pdf(pdf_url)

        assert result is not None
        assert output_dir.exists()


# ======================================================================
# TestExtractionLog
# ======================================================================


class TestExtractionLog:
    def test_empty_log(self, tmp_path):
        extractor = _make_extractor(tmp_path, log_file=tmp_path / "log.json")
        assert extractor._load_log() == []

    def test_round_trip(self, tmp_path):
        log_file = tmp_path / "log.json"
        extractor = _make_extractor(tmp_path, log_file=log_file)

        entries = [
            {"email_id": "abc", "status": "success"},
            {"email_id": "def", "status": "failed", "error": "No link"},
        ]
        extractor._save_log(entries)

        loaded = extractor._load_log()
        assert len(loaded) == 2
        assert loaded[0]["email_id"] == "abc"

    def test_processed_ids_filter(self, tmp_path):
        log_file = tmp_path / "log.json"
        log_file.write_text(
            json.dumps(
                [
                    {"email_id": "a", "status": "success"},
                    {"email_id": "b", "status": "failed"},
                    {"email_id": "c", "status": "success"},
                ]
            )
        )

        extractor = _make_extractor(tmp_path, log_file=log_file)
        ids = extractor._get_processed_ids()
        assert ids == {"a", "c"}


# ======================================================================
# Helpers
# ======================================================================


def _make_extractor(output_dir: Path, log_file: Path | None = None) -> GmailExtractor:
    """Create a GmailExtractor without authenticating (for unit tests)."""
    with patch.object(GmailExtractor, "_authenticate", return_value=None):
        extractor = GmailExtractor(
            output_dir=output_dir,
            log_file=log_file or output_dir / "extraction_log.json",
        )
    return extractor
