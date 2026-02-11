"""Normalize rider display names into stable, unique IDs."""

from __future__ import annotations

import re

TITLES = [
    "The Rt Hon",
    "The Hon",
    "Lt-Cdr",
    "Lt Cdr",
    "Maj-Gen",
    "Maj Gen",
    "Count",
    "Lord",
    "Sir",
    "Dr",
    "Prof",
]

# Sorted longest-first so longer prefixes match before shorter ones
TITLES_SORTED = sorted(TITLES, key=len, reverse=True)

PARTICLES = {"de", "di", "da", "von", "van", "du", "le", "la", "del"}

RE_INITIAL = re.compile(r"^([A-Za-z]\.)+$")
RE_QUALIFIER = re.compile(r"\((\w+)\)")


def normalize_rider_id(display_name: str) -> str:
    """Convert a display name into a stable, lowercase rider ID.

    Examples::

        "F.P. Rueda (Jnr)"               → "rueda_fp_jnr"
        "The Hon M.V.O. de C. Wrottesley" → "wrottesley_mvo_de_c"
        "Count F. Guerrini-Maraldi"        → "guerrini_maraldi_f"
        "Lord Doune"                       → "doune"
        "B.A.P. Bracher"                   → "bracher_bap"
    """
    name = display_name.strip()
    if not name:
        raise ValueError("Empty name")

    # Step 1 — Remove titles
    for title in TITLES_SORTED:
        pattern = re.compile(re.escape(title) + r"\s+", re.IGNORECASE)
        name = pattern.sub("", name, count=1)

    # Step 2 — Remove markers
    name = name.replace("(AM)", "").replace("(SL)", "").replace("**", "")
    # Also remove bare SL marker (word boundary)
    name = re.sub(r"\bSL\b", "", name)
    name = name.strip()

    if not name:
        raise ValueError(f"Empty name after cleanup: {display_name!r}")

    # Step 3 — Extract parenthetical qualifiers (e.g., Jnr, Snr)
    qualifier = None
    qual_match = RE_QUALIFIER.search(name)
    if qual_match:
        qualifier = qual_match.group(1).lower()
        name = RE_QUALIFIER.sub("", name).strip()

    # Step 4 — Tokenize
    tokens = name.split()

    if not tokens:
        raise ValueError(f"No tokens after cleanup: {display_name!r}")

    # Step 5 — Classify tokens
    classified: list[tuple[str, str]] = []  # (normalized, type)
    for token in tokens:
        if RE_INITIAL.match(token):
            # "M.V.O." → "mvo", "C." → "c"
            normalized = token.replace(".", "").lower()
            classified.append((normalized, "initial"))
        elif token.lower() in PARTICLES:
            classified.append((token.lower(), "particle"))
        else:
            # Surname token — hyphens become underscores
            normalized = token.lower().replace("-", "_")
            classified.append((normalized, "surname"))

    # Step 6 — Identify the surname (rightmost non-initial, non-particle)
    surname_idx = None
    for i in range(len(classified) - 1, -1, -1):
        if classified[i][1] == "surname":
            surname_idx = i
            break

    if surname_idx is None:
        # All tokens are initials/particles — treat last token as surname
        surname_idx = len(classified) - 1

    # Step 7 — Build ID: surname + remaining tokens in original order + qualifier
    parts = [classified[surname_idx][0]]
    for i, (normalized, _) in enumerate(classified):
        if i != surname_idx:
            parts.append(normalized)
    if qualifier:
        parts.append(qualifier)

    # Step 8 — Cleanup
    result = "_".join(parts)
    result = re.sub(r"_+", "_", result)
    result = result.strip("_")

    if not result:
        raise ValueError(f"Empty ID for name: {display_name!r}")

    return result
