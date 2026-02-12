"""Extract embedded race JSON from cresta-run.com event pages."""

from __future__ import annotations

import html
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Marker that precedes the race data JSON in the page's inline script.
_RACE_DATA_MARKER = 'const raceData = decodeHtml("'
_RACE_DATA_CLOSING = '");'


def extract_race_data(html_content: str) -> dict | None:
    """Extract the embedded race JSON from an event page's HTML.

    The page contains a line like:
        const raceData = decodeHtml("{...HTML-entity-encoded JSON...}");

    Returns:
        Parsed dict, or None if no data found or parsing fails.
    """
    start = html_content.find(_RACE_DATA_MARKER)
    if start == -1:
        return None

    start += len(_RACE_DATA_MARKER)

    end = html_content.find(_RACE_DATA_CLOSING, start)
    if end == -1:
        return None

    encoded = html_content[start:end]
    if not encoded.strip():
        return None

    try:
        decoded = html.unescape(encoded)
        return json.loads(decoded)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Failed to parse embedded race JSON: %s", e)
        return None


def has_ride_data(race_data: dict) -> bool:
    """Return True if the race data contains at least one ride."""
    rides = race_data.get("Rides")
    return isinstance(rides, list) and len(rides) > 0


def save_race_json(race_data: dict, output_dir: Path, filename: str) -> Path | None:
    """Save race data dict to a JSON file, skipping if it already exists.

    Returns:
        Path to the saved file, or None if file already existed.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename

    if output_path.exists():
        logger.debug("JSON already exists: %s", filename)
        return None

    output_path.write_text(json.dumps(race_data, indent=2))
    logger.info("Saved JSON: %s", filename)
    return output_path
