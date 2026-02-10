# Implementation Plan: Gmail → PDF Data Extraction Pipeline

> **Goal**: Build `gmail_extractor.py` — a module that authenticates with Gmail, finds Daily Results emails from `@cresta-run.com`, extracts the Mailchimp "click here" link from each email, follows the redirect to the actual PDF on Webflow CDN, and downloads every PDF into a local folder.
>
> **Current state**: OAuth credentials exist in `credentials/` and `test_gmail_auth.py` proves the Gmail API connection works (searches for emails, prints subjects). No extraction or download logic exists yet.
>
> **PRD reference**: `docs/toboggan-handicap-prd.md` — Phase 1: Data Pipeline

---

## Project Structure (target state after this plan)

```
smtc-handicap/
├── src/
│   └── gmail_extractor.py      # Main module (all steps below)
├── data/
│   └── raw_pdfs/               # Downloaded PDFs land here
├── credentials/
│   ├── client_secret_...json   # Already exists
│   └── gmail_token.json        # Already exists
├── tests/
│   └── test_gmail_extractor.py # Unit tests
├── requirements.txt            # Updated with new deps
├── test_gmail_auth.py          # Existing (keep as-is)
└── docs/
    └── ...
```

---

## Step 0: Environment Setup

### 0.1 — Update `requirements.txt`
Add the following dependencies (keep existing ones):
```
google-api-python-client
google-auth-httplib2
google-auth-oauthlib
requests
beautifulsoup4
lxml
```
- `requests` — for following Mailchimp redirects and downloading PDFs
- `beautifulsoup4` + `lxml` — for parsing HTML email bodies to find links

### 0.2 — Create directory structure
```bash
mkdir -p src data/raw_pdfs tests
touch src/__init__.py
```

### 0.3 — Install dependencies
```bash
pip install -r requirements.txt
```

---

## Step 1: Gmail Authentication (refactor from test script)

### What to build
Create `src/gmail_extractor.py` with a `GmailExtractor` class. The first piece is authentication — refactored from the existing `test_gmail_auth.py`.

### Acceptance criteria
- `GmailExtractor.__init__()` authenticates and stores a `self.service` object (the Gmail API client)
- Reuses existing token from `credentials/gmail_token.json` if valid
- Refreshes expired token automatically
- Opens browser for initial auth if no token exists
- Constants for `SCOPES`, `CREDENTIALS_FILE`, `TOKEN_FILE` at module level

### Implementation detail
```python
# src/gmail_extractor.py

from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDENTIALS_DIR = Path(__file__).parent.parent / "credentials"
CREDENTIALS_FILE = CREDENTIALS_DIR / "client_secret_476582044326-bk4gin0gc4our2gl9m5t3ntvkpafktsu.apps.googleusercontent.com.json"
TOKEN_FILE = CREDENTIALS_DIR / "gmail_token.json"

class GmailExtractor:
    def __init__(self):
        self.service = self._authenticate()

    def _authenticate(self) -> object:
        """Authenticate with Gmail API, returning a service object."""
        creds = None
        if TOKEN_FILE.exists():
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
                creds = flow.run_local_server(port=0)
            TOKEN_FILE.parent.mkdir(exist_ok=True)
            with open(TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
        return build("gmail", "v1", credentials=creds)
```

### How to verify
```python
extractor = GmailExtractor()
assert extractor.service is not None
```

---

## Step 2: Search Gmail for Daily Results Emails

### What to build
A method `search_emails()` that queries Gmail for all "Daily Results" emails from `@cresta-run.com`, handling pagination to get ALL results (not just the first page).

### Gmail API query
```
subject:"Daily Results" from:@cresta-run.com after:2020/01/01
```

### Acceptance criteria
- Returns a list of message IDs (strings)
- Handles pagination (`nextPageToken`) to fetch ALL matching emails, not just the first 100
- Accepts optional `after_date` parameter (default `"2020/01/01"`) to limit historical scope
- Logs how many emails were found

### Implementation detail
```python
def search_emails(self, after_date: str = "2020/01/01") -> list[str]:
    """
    Search for all Daily Results emails from cresta-run.com.

    Args:
        after_date: Only find emails after this date (YYYY/MM/DD format)

    Returns:
        List of Gmail message IDs
    """
    query = f'subject:"Daily Results" from:@cresta-run.com after:{after_date}'
    message_ids = []
    page_token = None

    while True:
        results = self.service.users().messages().list(
            userId="me",
            q=query,
            pageToken=page_token,
            maxResults=500  # max allowed by API
        ).execute()

        messages = results.get("messages", [])
        message_ids.extend(msg["id"] for msg in messages)

        page_token = results.get("nextPageToken")
        if not page_token:
            break

    print(f"Found {len(message_ids)} Daily Results emails")
    return message_ids
```

### How to verify
- Run and confirm it returns ~300+ message IDs (5 seasons × ~60 days)
- Spot-check a few by fetching their subjects to confirm they match the pattern

---

## Step 3: Fetch Email HTML Body

### What to build
A method `get_email_html(message_id)` that fetches a single email's full content and extracts the HTML body from the MIME parts.

### Key detail from PRD
Emails are HTML (Mailchimp template). The body is in the MIME structure, typically under `payload.parts` with `mimeType: "text/html"`. The content is base64url-encoded.

### Acceptance criteria
- Given a message ID, returns the HTML body as a decoded string
- Handles both simple (single-part) and multipart MIME structures
- Handles nested multipart (Mailchimp emails often have `multipart/alternative` inside `multipart/mixed`)

### Implementation detail
```python
import base64

def get_email_html(self, message_id: str) -> str | None:
    """Fetch and decode the HTML body of a Gmail message."""
    message = self.service.users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()

    return self._extract_html_from_payload(message["payload"])

def _extract_html_from_payload(self, payload: dict) -> str | None:
    """Recursively search MIME parts for text/html content."""
    mime_type = payload.get("mimeType", "")

    # Direct HTML body (simple message)
    if mime_type == "text/html":
        data = payload["body"].get("data", "")
        return base64.urlsafe_b64decode(data).decode("utf-8")

    # Multipart — recurse into parts
    if mime_type.startswith("multipart/"):
        for part in payload.get("parts", []):
            html = self._extract_html_from_payload(part)
            if html:
                return html

    return None
```

### How to verify
- Fetch HTML for 2-3 known email IDs
- Confirm the HTML contains "click here" text and `<a href=...>` tags
- Print a snippet to visually confirm it looks like a Mailchimp template

---

## Step 4: Extract the Results PDF Link from Email HTML

### What to build
A method `extract_results_link(html_body)` that parses the HTML and finds the hyperlink pointing to the results PDF (not the draw).

### Key details from PRD
- Link text patterns: `"For Today's results please click here"`, `"For today's results, please click here"`, etc.
- The `<a>` tag wraps "click here" (or just "here")
- There's also a **draw** link — we must SKIP that one
- Link URLs are either:
  - Mailchimp tracker: `https://cresta-run.us18.list-manage.com/track/click?u=...`
  - Direct CDN: `https://cdn.prod.website-files.com/.../*.pdf`

### Acceptance criteria
- Returns the URL string (Mailchimp tracker or direct CDN) for the **results** link
- Returns `None` if no results link found
- Does NOT return the draw link
- Handles variations in text casing and punctuation

### Implementation detail
```python
from bs4 import BeautifulSoup
from urllib.parse import unquote

def extract_results_link(self, html_body: str) -> str | None:
    """
    Extract the results PDF link from email HTML.

    Looks for "click here" links in the context of "results" text.
    Skips "draw" links.
    """
    soup = BeautifulSoup(html_body, "lxml")

    for link in soup.find_all("a", href=True):
        href = link["href"]
        link_text = link.get_text(strip=True).lower()
        # Get surrounding context (parent element text)
        parent_text = link.parent.get_text(separator=" ", strip=True).lower() if link.parent else ""

        # Strategy 1: Direct PDF link to Webflow CDN
        if "cdn.prod.website-files.com" in href and href.lower().endswith(".pdf"):
            if "draw" not in unquote(href).lower():
                return href

        # Strategy 2: "click here" / "here" in context of "results"
        if link_text in ("click here", "here"):
            if "result" in parent_text and "draw" not in parent_text:
                return href

    return None
```

### How to verify
- Run against 5-10 email HTML bodies from different dates
- Confirm each returns a URL (not `None`)
- Confirm none of the returned URLs contain "draw" in the decoded filename
- Print the URLs to visually confirm they look like Mailchimp tracker links or CDN URLs

---

## Step 5: Follow Mailchimp Redirect to Get Actual PDF URL

### What to build
A method `resolve_pdf_url(url)` that follows HTTP redirects from a Mailchimp tracking URL to the final Webflow CDN URL where the PDF lives.

### Key detail from PRD
```
Mailchimp tracker URL → HTTP 302 → Webflow CDN URL (the actual .pdf)
```
Example:
- Input: `https://cresta-run.us18.list-manage.com/track/click?u=84565b3a39...`
- Output: `https://cdn.prod.website-files.com/6683.../69736..._20260123%20pt%20%2B%20pj%20%2B%20splits.pdf`

### Acceptance criteria
- If input is already a CDN URL, return it as-is
- If input is a Mailchimp tracker, follow redirects and return the final URL
- Uses `HEAD` request (not `GET`) to avoid downloading the full PDF just to get the URL
- Falls back to `GET` if `HEAD` doesn't return the redirect properly
- Returns the final resolved URL as a string

### Implementation detail
```python
import requests

def resolve_pdf_url(self, url: str) -> str:
    """
    Follow redirects from a Mailchimp tracking URL to the final PDF URL.

    Returns the final URL after all redirects.
    """
    # Already a direct CDN link
    if "cdn.prod.website-files.com" in url:
        return url

    # Use HEAD to follow redirects without downloading
    try:
        response = requests.head(url, allow_redirects=True, timeout=15)
        response.raise_for_status()
        return response.url
    except requests.RequestException:
        # Fallback to GET if HEAD fails
        response = requests.get(url, allow_redirects=True, timeout=15, stream=True)
        response.raise_for_status()
        return response.url
```

### How to verify
- Resolve 3-5 Mailchimp URLs and confirm the final URLs:
  - Contain `cdn.prod.website-files.com`
  - End with `.pdf`
  - Have a valid date in the filename (YYYYMMDD)

---

## Step 6: Download PDF to Local Folder

### What to build
A method `download_pdf(pdf_url, output_dir)` that downloads the actual PDF bytes and saves to `data/raw_pdfs/` with a clean filename.

### Filename strategy
The CDN URL contains URL-encoded filenames like:
`69736fc8a00653a090a5668e_20260123%20pt%20%2B%20pj%20%2B%20splits.pdf`

We want to save as the decoded, human-readable version:
`20260123 pt + pj + splits.pdf`

Extract just the part after the last `_` in the URL path (the Webflow ID prefix is not useful).

### Acceptance criteria
- Downloads PDF content via `GET` request
- Saves to `data/raw_pdfs/{decoded_filename}`
- Skips download if file already exists (idempotent re-runs)
- Returns the local file path
- Validates that the downloaded content looks like a PDF (starts with `%PDF`)

### Implementation detail
```python
from urllib.parse import urlparse, unquote

PDF_OUTPUT_DIR = Path(__file__).parent.parent / "data" / "raw_pdfs"

def download_pdf(self, pdf_url: str, output_dir: Path | None = None) -> Path | None:
    """
    Download a PDF from the CDN URL and save locally.

    Returns the path to the saved file, or None if download failed.
    """
    output_dir = output_dir or PDF_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    # Extract clean filename from URL
    url_path = urlparse(pdf_url).path
    encoded_filename = url_path.split("/")[-1]
    decoded_filename = unquote(encoded_filename)

    # Strip the Webflow asset ID prefix (everything before first _)
    # e.g., "69736fc8a00653a090a5668e_20260123 pt + pj + splits.pdf"
    if "_" in decoded_filename:
        clean_filename = decoded_filename.split("_", 1)[1]
    else:
        clean_filename = decoded_filename

    output_path = output_dir / clean_filename

    # Skip if already downloaded
    if output_path.exists():
        print(f"  Already exists: {clean_filename}")
        return output_path

    # Download
    response = requests.get(pdf_url, timeout=30)
    response.raise_for_status()

    # Validate it's actually a PDF
    if not response.content[:5] == b"%PDF-":
        print(f"  WARNING: {clean_filename} does not appear to be a PDF")
        return None

    output_path.write_bytes(response.content)
    print(f"  Downloaded: {clean_filename} ({len(response.content)} bytes)")
    return output_path
```

### How to verify
- Download 2-3 PDFs and confirm:
  - Files appear in `data/raw_pdfs/`
  - Filenames are human-readable (e.g., `20260123 pt + pj + splits.pdf`)
  - Files open correctly in a PDF viewer
  - Re-running skips already-downloaded files

---

## Step 7: Orchestrate the Full Pipeline

### What to build
A method `run(after_date)` that chains all the steps together, plus a `__main__` block for CLI usage.

### Acceptance criteria
- Searches Gmail → iterates over all emails → extracts link → resolves URL → downloads PDF
- Handles errors gracefully per-email (log and continue to next, don't crash the whole run)
- Prints a summary at the end (total emails, successful downloads, skipped, failed)
- Stores a mapping of `{email_subject: pdf_path}` for traceability

### Implementation detail
```python
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

def run(self, after_date: str = "2020/01/01") -> dict:
    """
    Run the full extraction pipeline.

    Returns a summary dict with counts and any errors.
    """
    summary = {"total": 0, "downloaded": 0, "skipped": 0, "failed": 0, "errors": []}

    # Step 2: Search emails
    message_ids = self.search_emails(after_date=after_date)
    summary["total"] = len(message_ids)

    for i, msg_id in enumerate(message_ids, 1):
        logger.info(f"Processing email {i}/{len(message_ids)} (ID: {msg_id})")

        try:
            # Step 3: Get email HTML
            html = self.get_email_html(msg_id)
            if not html:
                logger.warning(f"  No HTML body found")
                summary["failed"] += 1
                summary["errors"].append({"msg_id": msg_id, "error": "No HTML body"})
                continue

            # Step 4: Extract results link
            link = self.extract_results_link(html)
            if not link:
                logger.warning(f"  No results link found")
                summary["failed"] += 1
                summary["errors"].append({"msg_id": msg_id, "error": "No results link"})
                continue

            # Step 5: Resolve Mailchimp redirect
            pdf_url = self.resolve_pdf_url(link)

            # Step 6: Download PDF
            result = self.download_pdf(pdf_url)
            if result and result.exists():
                summary["downloaded"] += 1
            else:
                summary["failed"] += 1

        except Exception as e:
            logger.error(f"  Error: {e}")
            summary["failed"] += 1
            summary["errors"].append({"msg_id": msg_id, "error": str(e)})

    # Print summary
    logger.info(f"\n{'='*50}")
    logger.info(f"Pipeline complete:")
    logger.info(f"  Total emails:  {summary['total']}")
    logger.info(f"  Downloaded:    {summary['downloaded']}")
    logger.info(f"  Failed:        {summary['failed']}")
    logger.info(f"{'='*50}")

    return summary
```

### CLI entry point
```python
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract PDFs from Cresta Run Daily Results emails")
    parser.add_argument("--after", default="2020/01/01", help="Only process emails after this date (YYYY/MM/DD)")
    parser.add_argument("--dry-run", action="store_true", help="Search and extract links but don't download")
    args = parser.parse_args()

    extractor = GmailExtractor()
    extractor.run(after_date=args.after)
```

### How to verify
- Run with `--after 2026/01/01` first (small batch, current season only) to test end-to-end
- Confirm PDFs appear in `data/raw_pdfs/`
- Check the summary output for any failures
- Then run with `--after 2020/01/01` for the full historical extraction

---

## Step 8: Add a Metadata/Tracking Log

### What to build
A simple JSON log file (`data/extraction_log.json`) that records every email processed and its outcome, so we can:
- Track which emails have been processed
- Debug failures
- Avoid reprocessing on subsequent runs

### Acceptance criteria
- Each entry contains: `email_id`, `email_subject`, `email_date`, `extracted_link`, `resolved_url`, `local_pdf_path`, `status` (success/failed/skipped), `error` (if any), `processed_at` timestamp
- Log is appended to (not overwritten) on each run
- Can be used to skip already-processed emails on re-runs

### Implementation detail
```python
import json
from datetime import datetime

LOG_FILE = Path(__file__).parent.parent / "data" / "extraction_log.json"

def _load_log(self) -> list[dict]:
    if LOG_FILE.exists():
        return json.loads(LOG_FILE.read_text())
    return []

def _save_log(self, log: list[dict]):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text(json.dumps(log, indent=2))

def _get_processed_ids(self) -> set[str]:
    """Return set of already-processed message IDs."""
    log = self._load_log()
    return {entry["email_id"] for entry in log if entry["status"] == "success"}
```

Update `run()` to:
1. Load processed IDs at start
2. Skip emails already in the log with status "success"
3. Append an entry for each email processed (success or failure)
4. Save the log at the end

### How to verify
- Run the pipeline twice
- Second run should skip all previously downloaded PDFs
- `data/extraction_log.json` should contain one entry per email

---

## Step 9: Unit Tests

### What to build
`tests/test_gmail_extractor.py` with tests that don't require live Gmail access.

### Tests to write

| Test | What it verifies |
|------|-----------------|
| `test_extract_results_link_mailchimp` | Parses a sample Mailchimp HTML email and finds the correct "click here" results link |
| `test_extract_results_link_direct_cdn` | Parses HTML with a direct CDN PDF link |
| `test_extract_results_link_skips_draw` | Confirms draw links are NOT returned |
| `test_extract_results_link_no_link` | Returns `None` for email without results link |
| `test_resolve_pdf_url_already_cdn` | Returns CDN URL unchanged |
| `test_download_pdf_skip_existing` | Doesn't re-download if file exists |
| `test_clean_filename_from_url` | Strips Webflow ID prefix and URL-decodes |

### Test fixtures
Create `tests/fixtures/` with 2-3 sample HTML email snippets (sanitized — no real tracking IDs). These can be extracted from real emails during Step 4 verification.

### How to verify
```bash
python -m pytest tests/test_gmail_extractor.py -v
```

---

## Step 10: End-to-End Validation

### 10.1 — Small batch test
```bash
python -m src.gmail_extractor --after 2026/01/01
```
- Expect: ~30-40 PDFs from the current (2026) season
- Verify: All files in `data/raw_pdfs/` are valid PDFs with readable filenames

### 10.2 — Full historical extraction
```bash
python -m src.gmail_extractor --after 2020/01/01
```
- Expect: ~300+ PDFs across 5 seasons
- Verify: Check `data/extraction_log.json` for failure rate
- Target: <5% failure rate (some emails may have unusual format)

### 10.3 — Spot-check results
Manually verify 5-10 PDFs:
- Open in a PDF viewer
- Confirm they contain race results / practice times / splits
- Confirm the filename date matches the PDF content date

---

## Dependency Chain

```
Step 0 (env setup)
  └─▶ Step 1 (auth)
       └─▶ Step 2 (search emails)
            └─▶ Step 3 (fetch HTML body)
                 └─▶ Step 4 (extract link from HTML)
                      └─▶ Step 5 (resolve redirect)
                           └─▶ Step 6 (download PDF)
                                └─▶ Step 7 (orchestrate pipeline)
                                     └─▶ Step 8 (tracking log)

Step 9 (tests) — can be written in parallel with Steps 4-8
Step 10 (validation) — after Step 8
```

---

## Edge Cases to Handle

| Edge case | How to handle |
|-----------|--------------|
| Email with no results link (e.g., cancellation notice) | Log as "no link found", skip |
| Mailchimp redirect returns non-PDF (HTML page) | Check `Content-Type` header or `%PDF-` magic bytes; log and skip |
| Duplicate emails (same day re-sent) | The filename-based dedup in Step 6 handles this (same date = same filename) |
| Email from new secretary (not in known senders) | Query uses `from:@cresta-run.com` domain match, not specific addresses |
| Rate limiting from Gmail API | Add a small delay between API calls (`time.sleep(0.1)`) if needed |
| Mailchimp tracking link expired | Log the error; consider extracting any alternative links |
| PDF URL returns 404 (CDN content removed) | Log and skip; the PDF may no longer be hosted |
| Very large PDF (>10MB) | No special handling needed, just download; `requests` handles this fine |

---

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/__init__.py` | CREATE | Empty file to make `src` a Python package |
| `src/gmail_extractor.py` | CREATE | Main module with `GmailExtractor` class (Steps 1-8) |
| `data/raw_pdfs/` | CREATE (dir) | Output directory for downloaded PDFs |
| `data/extraction_log.json` | AUTO-CREATED | Tracking log, created on first run |
| `tests/__init__.py` | CREATE | Empty file |
| `tests/test_gmail_extractor.py` | CREATE | Unit tests (Step 9) |
| `tests/fixtures/` | CREATE (dir) | Sample HTML email snippets for testing |
| `requirements.txt` | MODIFY | Add `requests`, `beautifulsoup4`, `lxml` |
| `.gitignore` | MODIFY | Add `data/raw_pdfs/`, `data/extraction_log.json` |

---

## Summary

This plan implements the **full Gmail → PDF download pipeline** in 10 incremental steps. Each step is independently testable. The final output is a `data/raw_pdfs/` folder containing ~300+ PDFs of Cresta Run race results, ready for the next phase (PDF parsing).

**To execute**: Hand this plan to a Claude Code instance with the instruction:
> "Read `docs/implementation-plan-data-extraction.md`. Verify the plan makes sense given the PRD in `docs/toboggan-handicap-prd.md` and the existing code. Then implement it step by step, testing each step before moving to the next."
