"""Webhook API for Gmail PDF extraction and ingestion."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Generator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from smtc_handicap.db import CrestaDB
from smtc_handicap.gmail_extractor import GmailExtractor
from smtc_handicap.pipeline import IngestStats, ingest_single_pdf

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "cresta.db"

app = FastAPI(title="SMTC Handicap API", version="0.1.0")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class WebhookRequest(BaseModel):
    sender: str = Field(..., description="Email sender address")
    subject: str = Field(..., description="Email subject line")
    timestamp: str = Field(..., description="ISO-8601 timestamp of the email")


class PdfIngestResult(BaseModel):
    pdf_filename: str
    races: int = 0
    riders: int = 0
    time_records: int = 0
    warnings: list[str] = Field(default_factory=list)
    re_ingested: bool = False


class WebhookResponse(BaseModel):
    status: str
    emails_found: int = 0
    pdfs_downloaded: int = 0
    pdfs_failed: int = 0
    ingestion_results: list[PdfIngestResult] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    db_counts: dict[str, int] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    db_counts: dict[str, int] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Dependencies (overridable in tests)
# ---------------------------------------------------------------------------


def get_db() -> Generator[CrestaDB, None, None]:
    db = CrestaDB(DB_PATH)
    try:
        yield db
    finally:
        db.close()


def get_extractor() -> GmailExtractor:
    return GmailExtractor()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def verify_api_key(x_api_key: Annotated[str | None, Header()] = None) -> str:
    expected = os.environ.get("SMTC_API_KEY")
    if not expected:
        raise HTTPException(status_code=500, detail="SMTC_API_KEY not configured")
    if x_api_key != expected:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    return x_api_key


# ---------------------------------------------------------------------------
# Query builder
# ---------------------------------------------------------------------------


def build_webhook_query(sender: str, subject: str, timestamp: str) -> str:
    """Build a Gmail search query scoped to a specific email.

    Uses a +/-1 day window around the timestamp so Gmail date filters
    (which are day-granularity) reliably match the target email.
    """
    dt = datetime.fromisoformat(timestamp)
    day_before = (dt - timedelta(days=1)).strftime("%Y/%m/%d")
    day_after = (dt + timedelta(days=1)).strftime("%Y/%m/%d")
    return f'from:{sender} subject:"{subject}" after:{day_before} before:{day_after}'


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


DbDep = Annotated[CrestaDB, Depends(get_db)]
ExtractorDep = Annotated[GmailExtractor, Depends(get_extractor)]


@app.get("/health", response_model=HealthResponse)
def health(db: DbDep):
    try:
        counts = db.get_counts()
        return HealthResponse(status="healthy", db_counts=counts)
    except Exception as exc:
        return HealthResponse(status=f"unhealthy: {exc}")


@app.post(
    "/webhook/ingest",
    response_model=WebhookResponse,
    dependencies=[Depends(verify_api_key)],
)
def webhook_ingest(
    payload: WebhookRequest,
    db: DbDep,
    extractor: ExtractorDep,
) -> WebhookResponse:
    resp = WebhookResponse(status="error")

    # 1. Search Gmail
    query = build_webhook_query(payload.sender, payload.subject, payload.timestamp)
    logger.info("Webhook query: %s", query)

    try:
        message_ids = extractor.search_emails(query=query)
    except Exception as exc:
        logger.error("Gmail API error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Gmail API error: {exc}") from exc

    resp.emails_found = len(message_ids)
    if not message_ids:
        resp.status = "no_email_found"
        resp.db_counts = db.get_counts()
        return resp

    # 2. For each email: extract PDF link, download, ingest
    downloaded: list[tuple[Path, str]] = []  # (pdf_path, msg_id)
    already_ingested = db.get_ingested_pdf_sources()

    for msg_id in message_ids:
        try:
            html = extractor.get_email_html(msg_id)
            if not html:
                resp.errors.append(f"No HTML body for message {msg_id}")
                resp.pdfs_failed += 1
                continue

            link = extractor.extract_pdf_link(html)
            if not link:
                resp.errors.append(f"No PDF link in message {msg_id}")
                resp.pdfs_failed += 1
                continue

            pdf_url = extractor.resolve_pdf_url(link)
            pdf_path = extractor.download_pdf(pdf_url, force=True)
            if not pdf_path or not pdf_path.exists():
                resp.errors.append(f"Download failed for message {msg_id}")
                resp.pdfs_failed += 1
                continue

            downloaded.append((pdf_path, msg_id))
            resp.pdfs_downloaded += 1
            time.sleep(0.05)

        except Exception as exc:
            logger.error("Error processing message %s: %s", msg_id, exc)
            resp.errors.append(f"Error processing message {msg_id}: {exc}")
            resp.pdfs_failed += 1

    if not downloaded and resp.emails_found > 0 and resp.pdfs_failed == 0:
        resp.status = "no_pdf_link"
        resp.db_counts = db.get_counts()
        return resp

    # 3. Ingest each downloaded PDF
    for pdf_path, _msg_id in downloaded:
        pdf_source = pdf_path.name
        re_ingested = pdf_source in already_ingested

        if re_ingested:
            deleted = db.delete_by_pdf_source(pdf_source)
            logger.info("Re-ingesting %s (deleted %d old records)", pdf_source, deleted)

        try:
            stats: IngestStats = ingest_single_pdf(db, pdf_path)
            result = PdfIngestResult(
                pdf_filename=pdf_source,
                races=stats.races_inserted,
                riders=stats.riders_upserted,
                time_records=stats.time_records_inserted,
                warnings=stats.warnings,
                re_ingested=re_ingested,
            )
            resp.ingestion_results.append(result)
        except Exception as exc:
            logger.error("Ingestion failed for %s: %s", pdf_source, exc)
            resp.errors.append(f"Ingestion failed for {pdf_source}: {exc}")

    # 4. Final status
    if resp.pdfs_downloaded > 0 and resp.pdfs_failed == 0:
        resp.status = "success"
    elif resp.pdfs_downloaded > 0 and resp.pdfs_failed > 0:
        resp.status = "partial"
    elif resp.pdfs_downloaded == 0 and resp.pdfs_failed > 0:
        resp.status = "error"

    resp.db_counts = db.get_counts()
    return resp
