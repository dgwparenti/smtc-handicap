"""Tests for the webhook API."""

from __future__ import annotations

import os
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed (install with [api])")
pytest.importorskip("httpx", reason="httpx not installed (install with [dev])")

pytestmark = pytest.mark.api

from fastapi.testclient import TestClient  # noqa: E402

from smtc_handicap.api import (  # noqa: E402
    app,
    build_webhook_query,
    get_db,
    get_extractor,
    verify_api_key,
)
from smtc_handicap.db import CrestaDB  # noqa: E402

API_KEY = "test-secret-key"

# Sample HTML containing a PDF link
SAMPLE_HTML = (
    "<html><body><p>Results attached, please"
    ' <a href="https://cdn.prod.website-files.com/abc_20260224-results.pdf">click here</a>'
    " to view.</p></body></html>"
)

# Sample HTML with no PDF link
NO_LINK_HTML = "<html><body><p>No results today.</p></body></html>"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def in_memory_db():
    """Create an in-memory CrestaDB for testing.

    Uses check_same_thread=False because FastAPI runs sync endpoints
    in a worker thread, while the fixture is created in the test thread.
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA foreign_keys=ON")
    db = CrestaDB.__new__(CrestaDB)
    db.db_path = ":memory:"
    db.conn = conn
    db._create_tables()
    yield db
    db.close()


@pytest.fixture()
def mock_extractor():
    """Return a MagicMock standing in for GmailExtractor."""
    return MagicMock()


def _db_override(db):
    """Generator override matching the get_db() dependency signature."""

    def override():
        yield db

    return override


@pytest.fixture()
def client(in_memory_db, mock_extractor):
    """FastAPI TestClient with dependency overrides."""
    app.dependency_overrides[get_db] = _db_override(in_memory_db)
    app.dependency_overrides[get_extractor] = lambda: mock_extractor
    app.dependency_overrides[verify_api_key] = lambda: API_KEY

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture()
def authed_client(in_memory_db, mock_extractor):
    """TestClient that requires real API key validation."""
    app.dependency_overrides[get_db] = _db_override(in_memory_db)
    app.dependency_overrides[get_extractor] = lambda: mock_extractor
    # Do NOT override verify_api_key — real auth check

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


def _make_payload(**overrides) -> dict:
    base = {
        "sender": "annabel.kettler@cresta-run.com",
        "subject": "Daily Results - 24th Feb",
        "timestamp": "2026-02-24T13:16:56Z",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


class TestAuth:
    def test_missing_api_key_returns_403(self, authed_client):
        os.environ["SMTC_API_KEY"] = API_KEY
        try:
            resp = authed_client.post("/webhook/ingest", json=_make_payload())
            assert resp.status_code == 403
        finally:
            os.environ.pop("SMTC_API_KEY", None)

    def test_invalid_api_key_returns_403(self, authed_client):
        os.environ["SMTC_API_KEY"] = API_KEY
        try:
            resp = authed_client.post(
                "/webhook/ingest",
                json=_make_payload(),
                headers={"X-API-Key": "wrong-key"},
            )
            assert resp.status_code == 403
        finally:
            os.environ.pop("SMTC_API_KEY", None)

    def test_valid_api_key_passes(self, authed_client, mock_extractor):
        os.environ["SMTC_API_KEY"] = API_KEY
        mock_extractor.search_emails.return_value = []
        try:
            resp = authed_client.post(
                "/webhook/ingest",
                json=_make_payload(),
                headers={"X-API-Key": API_KEY},
            )
            assert resp.status_code == 200
        finally:
            os.environ.pop("SMTC_API_KEY", None)

    def test_unconfigured_api_key_returns_500(self, authed_client):
        os.environ.pop("SMTC_API_KEY", None)
        resp = authed_client.post(
            "/webhook/ingest",
            json=_make_payload(),
            headers={"X-API-Key": "anything"},
        )
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Webhook endpoint tests
# ---------------------------------------------------------------------------


class TestWebhookIngest:
    def test_no_email_found(self, client, mock_extractor):
        mock_extractor.search_emails.return_value = []

        resp = client.post("/webhook/ingest", json=_make_payload())
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "no_email_found"
        assert data["emails_found"] == 0

    def test_email_found_no_pdf_link(self, client, mock_extractor):
        mock_extractor.search_emails.return_value = ["msg-1"]
        mock_extractor.get_email_html.return_value = NO_LINK_HTML
        mock_extractor.extract_pdf_link.return_value = None

        resp = client.post("/webhook/ingest", json=_make_payload())
        assert resp.status_code == 200
        data = resp.json()
        # pdfs_failed > 0 because we couldn't extract a link
        assert data["emails_found"] == 1
        assert data["pdfs_failed"] == 1

    def test_email_found_no_html(self, client, mock_extractor):
        mock_extractor.search_emails.return_value = ["msg-1"]
        mock_extractor.get_email_html.return_value = None

        resp = client.post("/webhook/ingest", json=_make_payload())
        assert resp.status_code == 200
        data = resp.json()
        assert data["pdfs_failed"] == 1
        assert any("No HTML body" in e for e in data["errors"])

    def test_successful_download_and_ingest(self, client, mock_extractor, tmp_path):
        # Create a fake PDF file
        pdf_file = tmp_path / "20260224-results.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake pdf content")

        mock_extractor.search_emails.return_value = ["msg-1"]
        mock_extractor.get_email_html.return_value = SAMPLE_HTML
        mock_extractor.extract_pdf_link.return_value = (
            "https://cdn.prod.website-files.com/abc_20260224-results.pdf"
        )
        mock_extractor.resolve_pdf_url.return_value = (
            "https://cdn.prod.website-files.com/abc_20260224-results.pdf"
        )
        mock_extractor.download_pdf.return_value = pdf_file

        with patch("smtc_handicap.api.ingest_single_pdf") as mock_ingest:
            from smtc_handicap.pipeline import IngestStats

            mock_ingest.return_value = IngestStats(
                pdfs_processed=1,
                races_inserted=2,
                riders_upserted=50,
                time_records_inserted=120,
                warnings=[],
            )

            resp = client.post("/webhook/ingest", json=_make_payload())

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["emails_found"] == 1
        assert data["pdfs_downloaded"] == 1
        assert data["pdfs_failed"] == 0
        assert len(data["ingestion_results"]) == 1

        result = data["ingestion_results"][0]
        assert result["pdf_filename"] == "20260224-results.pdf"
        assert result["races"] == 2
        assert result["riders"] == 50
        assert result["time_records"] == 120
        assert result["re_ingested"] is False

    def test_re_ingestion(self, client, mock_extractor, in_memory_db, tmp_path):
        """If the PDF source already exists in DB, delete old data and re-ingest."""
        # Pre-populate DB with a race from this PDF source
        import datetime

        from smtc_handicap.models import Race, Rider, TimeRecord

        rider = Rider(
            rider_id="smith-john",
            display_name="John Smith",
            nationality="GBR",
            is_sl=False,
            is_am=False,
            first_seen_date=datetime.date(2026, 1, 1),
        )
        in_memory_db.upsert_rider(rider)

        race = Race(
            race_id="old-race-1",
            name="Practice Top",
            date=datetime.date(2026, 2, 24),
            start_position="TOP",
            is_handicap_race=False,
            is_practice=True,
            day_number=1,
            pdf_source="20260224-results.pdf",
        )
        in_memory_db.insert_race(race)

        record = TimeRecord(
            record_id="old-rec-1",
            race_id="old-race-1",
            rider_id="smith-john",
            run_number=1,
            finish_time=55.0,
        )
        in_memory_db.insert_time_record(record)

        # Now trigger webhook
        pdf_file = tmp_path / "20260224-results.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")

        mock_extractor.search_emails.return_value = ["msg-1"]
        mock_extractor.get_email_html.return_value = SAMPLE_HTML
        mock_extractor.extract_pdf_link.return_value = "https://example.com/results.pdf"
        mock_extractor.resolve_pdf_url.return_value = "https://example.com/results.pdf"
        mock_extractor.download_pdf.return_value = pdf_file

        with patch("smtc_handicap.api.ingest_single_pdf") as mock_ingest:
            from smtc_handicap.pipeline import IngestStats

            mock_ingest.return_value = IngestStats(
                pdfs_processed=1,
                races_inserted=3,
                riders_upserted=60,
                time_records_inserted=150,
            )

            resp = client.post("/webhook/ingest", json=_make_payload())

        data = resp.json()
        assert data["status"] == "success"
        result = data["ingestion_results"][0]
        assert result["re_ingested"] is True

    def test_partial_failure(self, client, mock_extractor, tmp_path):
        """One email downloads OK, another fails → status=partial."""
        pdf_file = tmp_path / "20260224-results.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")

        mock_extractor.search_emails.return_value = ["msg-1", "msg-2"]
        mock_extractor.get_email_html.side_effect = [SAMPLE_HTML, SAMPLE_HTML]
        mock_extractor.extract_pdf_link.side_effect = [
            "https://example.com/results.pdf",
            "https://example.com/other.pdf",
        ]
        mock_extractor.resolve_pdf_url.side_effect = [
            "https://example.com/results.pdf",
            Exception("SSL error"),
        ]
        mock_extractor.download_pdf.return_value = pdf_file

        with patch("smtc_handicap.api.ingest_single_pdf") as mock_ingest:
            from smtc_handicap.pipeline import IngestStats

            mock_ingest.return_value = IngestStats(
                pdfs_processed=1,
                races_inserted=1,
                riders_upserted=10,
                time_records_inserted=30,
            )

            resp = client.post("/webhook/ingest", json=_make_payload())

        data = resp.json()
        assert data["status"] == "partial"
        assert data["pdfs_downloaded"] == 1
        assert data["pdfs_failed"] == 1
        assert data["emails_found"] == 2

    def test_gmail_api_error_returns_502(self, client, mock_extractor):
        mock_extractor.search_emails.side_effect = Exception("Gmail quota exceeded")

        resp = client.post("/webhook/ingest", json=_make_payload())
        assert resp.status_code == 502
        assert "Gmail API error" in resp.json()["detail"]

    def test_download_failure_returns_error(self, client, mock_extractor):
        mock_extractor.search_emails.return_value = ["msg-1"]
        mock_extractor.get_email_html.return_value = SAMPLE_HTML
        mock_extractor.extract_pdf_link.return_value = "https://example.com/results.pdf"
        mock_extractor.resolve_pdf_url.return_value = "https://example.com/results.pdf"
        mock_extractor.download_pdf.return_value = None  # download failed

        resp = client.post("/webhook/ingest", json=_make_payload())
        data = resp.json()
        assert data["pdfs_failed"] == 1
        assert data["pdfs_downloaded"] == 0


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


class TestHealth:
    def test_healthy(self, client, in_memory_db):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "riders" in data["db_counts"]
        assert "races" in data["db_counts"]
        assert "time_records" in data["db_counts"]


# ---------------------------------------------------------------------------
# Query builder
# ---------------------------------------------------------------------------


class TestBuildWebhookQuery:
    def test_basic_query(self):
        query = build_webhook_query(
            sender="annabel.kettler@cresta-run.com",
            subject="Daily Results - 24th Feb",
            timestamp="2026-02-24T13:16:56Z",
        )
        assert "from:annabel.kettler@cresta-run.com" in query
        assert 'subject:"Daily Results - 24th Feb"' in query
        assert "after:2026/02/23" in query
        assert "before:2026/02/25" in query

    def test_date_window_crosses_month_boundary(self):
        query = build_webhook_query(
            sender="test@example.com",
            subject="Results",
            timestamp="2026-03-01T08:00:00Z",
        )
        assert "after:2026/02/28" in query
        assert "before:2026/03/02" in query
