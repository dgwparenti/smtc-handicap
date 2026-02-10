#!/usr/bin/env python3
"""One-time script to capture real email HTML bodies as test fixtures.

Usage:
    python scripts/create_test_fixtures.py

Requires Gmail credentials to be set up (run gmail_auth_check.py first).
Saves HTML fixtures to tests/fixtures/ for use in functional tests.
"""

from __future__ import annotations

import logging
from pathlib import Path

from smtc_handicap.gmail_extractor import GmailExtractor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def main() -> None:
    extractor = GmailExtractor()
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    ids = extractor.search_emails(after_date="2026/01/01")
    logger.info("Found %d emails to sample from", len(ids))

    saved = 0
    for msg_id in ids[:20]:
        metadata = extractor.get_email_metadata(msg_id)
        html = extractor.get_email_html(msg_id)
        if not html:
            continue

        subject = metadata["subject"]
        link = extractor.extract_pdf_link(html)

        # Determine fixture type
        if link and "list-manage.com" in link:
            fixture_type = "mailchimp_link"
        elif link and "cdn.prod.website-files.com" in link:
            fixture_type = "direct_cdn"
        elif not link:
            fixture_type = "no_link"
        else:
            fixture_type = "other"

        filename = f"real_email_{fixture_type}_{msg_id[:8]}.html"
        filepath = FIXTURES_DIR / filename
        filepath.write_text(html)
        logger.info("Saved: %s (%s) — %s", filename, fixture_type, subject)

        saved += 1
        if saved >= 6:
            break

    logger.info("Done. Saved %d fixtures to %s", saved, FIXTURES_DIR)


if __name__ == "__main__":
    main()
