"""Integration tests requiring live Gmail API access.

Run with:  pytest -m integration -v
Skip with: pytest -m 'not integration'
"""

from __future__ import annotations

import pytest

from smtc_handicap.gmail_extractor import GmailExtractor

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def extractor():
    """Create a real GmailExtractor (requires credentials on disk)."""
    return GmailExtractor()


class TestAuthentication:
    def test_authentication_succeeds(self, extractor):
        assert extractor.service is not None


class TestSearch:
    def test_search_returns_messages(self, extractor):
        ids = extractor.search_emails(after_date="2026/01/01")
        assert len(ids) > 0

    def test_search_pagination(self, extractor):
        ids = extractor.search_emails(after_date="2020/01/01")
        # Expect hundreds of results across multiple seasons
        assert len(ids) > 100


class TestEmailContent:
    def test_get_email_html_returns_content(self, extractor):
        ids = extractor.search_emails(after_date="2026/01/01")
        assert len(ids) > 0

        html = extractor.get_email_html(ids[0])
        assert html is not None
        assert "<" in html  # Contains HTML tags

    def test_extract_link_from_real_email(self, extractor):
        ids = extractor.search_emails(after_date="2026/01/01")
        assert len(ids) > 0

        html = extractor.get_email_html(ids[0])
        assert html is not None

        link = extractor.extract_pdf_link(html)
        # Link may be None for cancellation emails, but most should have one
        if link is not None:
            assert "http" in link


class TestResolveAndDownload:
    def test_resolve_real_mailchimp_url(self, extractor):
        ids = extractor.search_emails(after_date="2026/01/01")
        assert len(ids) > 0

        # Find an email with a link
        for msg_id in ids[:10]:
            html = extractor.get_email_html(msg_id)
            if html:
                link = extractor.extract_pdf_link(html)
                if link:
                    resolved = extractor.resolve_pdf_url(link)
                    assert resolved.lower().endswith(".pdf") or "cdn" in resolved
                    return

        pytest.skip("No email with results link found in first 10 messages")

    def test_download_single_pdf(self, extractor, tmp_path):
        ids = extractor.search_emails(after_date="2026/01/01")
        assert len(ids) > 0

        for msg_id in ids[:10]:
            html = extractor.get_email_html(msg_id)
            if html:
                link = extractor.extract_pdf_link(html)
                if link:
                    pdf_url = extractor.resolve_pdf_url(link)
                    extractor.output_dir = tmp_path
                    result = extractor.download_pdf(pdf_url)
                    assert result is not None
                    assert result.exists()
                    assert result.stat().st_size > 0
                    return

        pytest.skip("No downloadable PDF found in first 10 messages")

    def test_full_pipeline_small_batch(self, extractor, tmp_path):
        extractor.output_dir = tmp_path
        extractor.log_file = tmp_path / "extraction_log.json"

        summary = extractor.run(after_date="2026/02/01")

        assert summary["total"] > 0
        assert summary["downloaded"] + summary["skipped"] + summary["failed"] == summary["total"]
