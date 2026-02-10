# SMTC Handicap

Bayesian modelling for handicapping toboggan races on the Cresta Run.

Manual handicapping for Cresta Run races relies on committee judgment, which is time-consuming and inconsistent. This system uses Bayesian statistics to generate fair handicaps that bring all riders within competitive parity.

## Architecture

```
Gmail Inbox (Daily Results emails)
    |
    v
gmail_extractor — search emails, extract PDF links, download results
    |
    v
pdf_parser — parse practice/race/split results from PDFs
    |
    v
data_store (SQLite) — races, riders, time records
    |
    v
bayesian_model — fit rider ability distributions, generate handicaps
    |
    v
Output — Excel/CSV handicap sheets for committee
```

## Setup

Requires Python 3.11+.

```bash
# Clone and install in editable mode with dev dependencies
git clone https://github.com/dgwparenti/smtc-handicap.git
cd smtc-handicap
pip install -e ".[dev]"
```

## Development

```bash
# Run tests
pytest --verbose

# Lint
ruff check src/ tests/

# Check formatting
ruff format --check src/ tests/

# Auto-fix formatting
ruff format src/ tests/
```

## MVP Roadmap

1. **Data Pipeline** — Gmail auth, email search, link extraction, PDF download
2. **Parsing Engine** — Practice/race/split parsers, rider name normalization
3. **Data Storage** — SQLite schema, import pipeline, query interface
4. **Bayesian Model** — Rider ability distributions, handicap calculation
5. **Reporting** — Excel export, rider summaries, comparison with committee handicaps

See [docs/toboggan-handicap-prd.md](docs/toboggan-handicap-prd.md) for the full product requirements.

## License

Copyright (c) 2026 Daniele Parenti
All rights reserved.

Permission is granted to view, run, and modify this software
for personal, educational, and non-commercial purposes only.

Commercial use, distribution, sublicensing, or offering this
software as part of a paid product or service is prohibited
without prior written permission from the copyright holder.

The copyright holder may offer separate commercial licenses.
