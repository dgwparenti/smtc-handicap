"""Gmail-to-PDF data extraction pipeline for Cresta Run Daily Results emails."""

from __future__ import annotations

import argparse
import base64
import json
import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CREDENTIALS_FILE = (
    PROJECT_ROOT
    / "credentials"
    / "client_secret_476582044326-bk4gin0gc4our2gl9m5t3ntvkpafktsu.apps.googleusercontent.com.json"
)
TOKEN_FILE = PROJECT_ROOT / "credentials" / "gmail_token.json"
PDF_OUTPUT_DIR = PROJECT_ROOT / "data" / "raw_pdfs"
LOG_FILE = PROJECT_ROOT / "data" / "extraction_log.json"


class GmailExtractor:
    """Downloads race result PDFs from Gmail Daily Results emails."""

    def __init__(
        self,
        credentials_file: Path | None = None,
        token_file: Path | None = None,
        output_dir: Path | None = None,
        log_file: Path | None = None,
    ):
        self.credentials_file = credentials_file or CREDENTIALS_FILE
        self.token_file = token_file or TOKEN_FILE
        self.output_dir = output_dir or PDF_OUTPUT_DIR
        self.log_file = log_file or LOG_FILE
        self.service = self._authenticate()

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _authenticate(self):
        """Authenticate with Gmail API, returning a service object."""
        creds = None
        if self.token_file.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_file), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing expired token...")
                creds.refresh(Request())
            else:
                logger.info("Opening browser for authentication...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_file), SCOPES
                )
                creds = flow.run_local_server(port=0)

            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.token_file, "w") as f:
                f.write(creds.to_json())

        return build("gmail", "v1", credentials=creds)

    # ------------------------------------------------------------------
    # Email search
    # ------------------------------------------------------------------

    def search_emails(self, after_date: str = "2020/01/01") -> list[str]:
        """Search for all Daily Results emails from cresta-run.com.

        Args:
            after_date: Only find emails after this date (YYYY/MM/DD format).

        Returns:
            List of Gmail message IDs.
        """
        query = f'subject:"Daily Results" from:@cresta-run.com after:{after_date}'
        message_ids: list[str] = []
        page_token = None

        while True:
            results = (
                self.service.users()
                .messages()
                .list(userId="me", q=query, pageToken=page_token, maxResults=500)
                .execute()
            )

            messages = results.get("messages", [])
            message_ids.extend(msg["id"] for msg in messages)

            page_token = results.get("nextPageToken")
            if not page_token:
                break

        logger.info("Found %d Daily Results emails", len(message_ids))
        return message_ids

    # ------------------------------------------------------------------
    # Email body retrieval
    # ------------------------------------------------------------------

    def get_email_metadata(self, message_id: str) -> dict[str, str]:
        """Fetch subject and date headers for a Gmail message."""
        message = (
            self.service.users()
            .messages()
            .get(userId="me", id=message_id, format="metadata")
            .execute()
        )
        headers = {h["name"]: h["value"] for h in message["payload"]["headers"]}
        return {
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
        }

    def get_email_html(self, message_id: str) -> str | None:
        """Fetch and decode the HTML body of a Gmail message."""
        message = (
            self.service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        return self._extract_html_from_payload(message["payload"])

    @staticmethod
    def _extract_html_from_payload(payload: dict) -> str | None:
        """Recursively search MIME parts for text/html content."""
        mime_type = payload.get("mimeType", "")

        if mime_type == "text/html":
            data = payload["body"].get("data", "")
            return base64.urlsafe_b64decode(data).decode("utf-8")

        if mime_type.startswith("multipart/"):
            for part in payload.get("parts", []):
                html = GmailExtractor._extract_html_from_payload(part)
                if html:
                    return html

        return None

    # ------------------------------------------------------------------
    # Link extraction
    # ------------------------------------------------------------------

    @staticmethod
    def extract_results_link(html_body: str) -> str | None:
        """Extract the results PDF link from email HTML.

        Finds "click here"/"here" anchors in "results" context.
        Skips draw links. Also recognises direct CDN URLs.
        """
        soup = BeautifulSoup(html_body, "lxml")

        for link in soup.find_all("a", href=True):
            href = link["href"]
            link_text = link.get_text(strip=True).lower()
            parent_text = (
                link.parent.get_text(separator=" ", strip=True).lower() if link.parent else ""
            )

            # Strategy 1: Direct PDF link to Webflow CDN
            if (
                "cdn.prod.website-files.com" in href
                and href.lower().endswith(".pdf")
                and "draw" not in unquote(href).lower()
            ):
                return href

            # Strategy 2: "click here" / "here" in context of "results"
            if (
                link_text in ("click here", "here")
                and "result" in parent_text
                and "draw" not in parent_text
            ):
                return href

        return None

    # ------------------------------------------------------------------
    # Redirect resolution
    # ------------------------------------------------------------------

    @staticmethod
    def resolve_pdf_url(url: str) -> str:
        """Follow redirects from a Mailchimp tracking URL to the final PDF URL."""
        if "cdn.prod.website-files.com" in url:
            return url

        try:
            response = requests.head(url, allow_redirects=True, timeout=15)
            response.raise_for_status()
            return response.url
        except requests.exceptions.SSLError:
            logger.warning("SSL verification failed for %s — retrying without verification", url)
            response = requests.head(url, allow_redirects=True, timeout=15, verify=False)
            response.raise_for_status()
            return response.url
        except requests.RequestException:
            response = requests.get(url, allow_redirects=True, timeout=15, stream=True)
            response.raise_for_status()
            return response.url

    # ------------------------------------------------------------------
    # Filename handling
    # ------------------------------------------------------------------

    @staticmethod
    def clean_filename(pdf_url: str) -> str:
        """Strip Webflow asset ID prefix and URL-decode the filename."""
        url_path = urlparse(pdf_url).path
        encoded_filename = url_path.split("/")[-1]
        decoded_filename = unquote(encoded_filename)

        if "_" in decoded_filename:
            return decoded_filename.split("_", 1)[1]
        return decoded_filename

    @staticmethod
    def parse_pdf_filename(filename: str) -> dict:
        """Extract date and event metadata from a PDF filename.

        Filenames look like: ``20260123 pt + pj + splits.pdf``

        Event codes:
            rt = Race Top (Top Race Open)
            rj = Race Junction (Junction Race Open)
            pt = Practice Top
            pj = Practice Junction
            rth = Race Top Handicap
            rjh = Race Junction Handicap
            splits = Splits data included

        Returns:
            Dict with ``date``, ``events`` list, and ``has_splits`` bool.
        """
        stem = Path(filename).stem
        date_match = re.match(r"(\d{8})", stem)
        date_str = date_match.group(1) if date_match else None

        remainder = stem[8:].strip() if date_str else stem
        tokens = [t.strip().lower() for t in remainder.split("+")]

        has_splits = "splits" in tokens
        events = [t for t in tokens if t and t != "splits"]

        return {
            "date": date_str,
            "events": events,
            "has_splits": has_splits,
        }

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_pdf(self, pdf_url: str) -> Path | None:
        """Download a PDF from the CDN URL and save locally.

        Returns the path to the saved file, or None if download failed.
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)

        clean_name = self.clean_filename(pdf_url)
        output_path = self.output_dir / clean_name

        if output_path.exists():
            logger.info("  Already exists: %s", clean_name)
            return output_path

        try:
            response = requests.get(pdf_url, timeout=30)
        except requests.exceptions.SSLError:
            logger.warning("SSL verification failed for download — retrying without verification")
            response = requests.get(pdf_url, timeout=30, verify=False)
        response.raise_for_status()

        if response.content[:5] != b"%PDF-":
            logger.warning("  %s does not appear to be a PDF", clean_name)
            return None

        output_path.write_bytes(response.content)
        logger.info("  Downloaded: %s (%d bytes)", clean_name, len(response.content))
        return output_path

    # ------------------------------------------------------------------
    # Extraction log (idempotency)
    # ------------------------------------------------------------------

    def _load_log(self) -> list[dict]:
        if self.log_file.exists():
            return json.loads(self.log_file.read_text())
        return []

    def _save_log(self, log: list[dict]) -> None:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.log_file.write_text(json.dumps(log, indent=2))

    def _get_processed_ids(self) -> set[str]:
        """Return set of already-processed message IDs."""
        log = self._load_log()
        return {entry["email_id"] for entry in log if entry["status"] == "success"}

    # ------------------------------------------------------------------
    # Pipeline orchestration
    # ------------------------------------------------------------------

    def run(self, after_date: str = "2020/01/01", *, dry_run: bool = False) -> dict:
        """Run the full extraction pipeline.

        Returns a summary dict with counts and any errors.
        """
        summary: dict = {
            "total": 0,
            "downloaded": 0,
            "skipped": 0,
            "failed": 0,
            "errors": [],
        }

        message_ids = self.search_emails(after_date=after_date)
        summary["total"] = len(message_ids)

        processed_ids = self._get_processed_ids()
        log = self._load_log()

        for i, msg_id in enumerate(message_ids, 1):
            if msg_id in processed_ids:
                logger.debug("Skipping already-processed email %s", msg_id)
                summary["skipped"] += 1
                continue

            logger.info("Processing email %d/%d (ID: %s)", i, len(message_ids), msg_id)

            entry: dict = {
                "email_id": msg_id,
                "processed_at": datetime.now(UTC).isoformat(),
                "status": "failed",
            }

            try:
                metadata = self.get_email_metadata(msg_id)
                entry["email_subject"] = metadata["subject"]
                entry["email_date"] = metadata["date"]

                html = self.get_email_html(msg_id)
                if not html:
                    entry["error"] = "No HTML body"
                    logger.warning("  No HTML body found")
                    summary["failed"] += 1
                    log.append(entry)
                    time.sleep(0.1)
                    continue

                link = self.extract_results_link(html)
                entry["extracted_link"] = link
                if not link:
                    entry["error"] = "No results link"
                    logger.warning("  No results link found")
                    summary["failed"] += 1
                    log.append(entry)
                    time.sleep(0.1)
                    continue

                if dry_run:
                    logger.info("  [dry-run] Would download: %s", link)
                    entry["status"] = "dry_run"
                    log.append(entry)
                    time.sleep(0.1)
                    continue

                pdf_url = self.resolve_pdf_url(link)
                entry["resolved_url"] = pdf_url

                result = self.download_pdf(pdf_url)
                if result and result.exists():
                    entry["local_pdf_path"] = str(result)
                    entry["status"] = "success"
                    summary["downloaded"] += 1
                else:
                    entry["error"] = "Download failed or invalid PDF"
                    summary["failed"] += 1

            except Exception as e:
                logger.error("  Error: %s", e)
                entry["error"] = str(e)
                summary["failed"] += 1

            log.append(entry)
            time.sleep(0.1)

        self._save_log(log)

        logger.info("=" * 50)
        logger.info("Pipeline complete:")
        logger.info("  Total emails:  %d", summary["total"])
        logger.info("  Downloaded:    %d", summary["downloaded"])
        logger.info("  Skipped:       %d", summary["skipped"])
        logger.info("  Failed:        %d", summary["failed"])
        logger.info("=" * 50)

        return summary


def main() -> None:
    """CLI entry point for the Gmail extraction pipeline."""
    parser = argparse.ArgumentParser(
        description="Extract PDFs from Cresta Run Daily Results emails"
    )
    parser.add_argument(
        "--after",
        default="2020/01/01",
        help="Only process emails after this date (YYYY/MM/DD)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Search and extract links but don't download",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    extractor = GmailExtractor()
    extractor.run(after_date=args.after, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
