# Plan: PDF Data Extraction, Data Model & SQLite Database

## Context

The Cresta Run handicapping system needs to extract toboggan race results from downloaded PDFs (daily results from the Cresta Run), store them in a local relational database, and make the data available for downstream Bayesian modelling. The PRD (`docs/toboggan-handicap-prd.md`) defines three core data entities (Race, Rider, TimeRecord), the PDF structure, and parsing rules. Gmail auth already works (`test_gmail_auth.py`). No parsing, database, or data model code exists yet.

This plan covers **PRD Phases 2 & 3**: building the parsing engine, data model, SQLite schema, and ingestion pipeline.

---

## 1. Project Structure (new files to create)

```
smtc-handicap/
├── data/
│   └── raw_pdfs/              # PDFs go here (gitignored)
│       └── .gitkeep
├── src/
│   └── smtc_handicap/
│       ├── __init__.py        # EXISTS
│       ├── models.py          # NEW: dataclasses (Race, Rider, TimeRecord)
│       ├── name_normalizer.py # NEW: rider name → normalized ID
│       ├── filename_parser.py # NEW: extract metadata from PDF filename
│       ├── pdf_parser.py      # NEW: pdfplumber-based section detection + parsing
│       ├── db.py              # NEW: SQLite schema + CRUD operations
│       └── pipeline.py        # NEW: orchestrator (read PDFs → parse → store)
├── scripts/
│   ├── ingest_pdfs.py         # NEW: CLI entry point to run the pipeline
│   └── inspect_db.py          # NEW: debug script to print DB contents
└── tests/
    ├── conftest.py            # UPDATE: add shared fixtures
    ├── test_models.py         # NEW
    ├── test_name_normalizer.py# NEW
    ├── test_filename_parser.py# NEW
    ├── test_pdf_parser.py     # NEW
    ├── test_db.py             # NEW
    └── fixtures/              # NEW: sample PDFs for integration tests
```

**Implementation order** (each step builds on the previous):

1. `name_normalizer.py` + tests
2. `models.py` + tests
3. `filename_parser.py` + tests
4. `db.py` + tests
5. `pdf_parser.py` + tests
6. `pipeline.py` + scripts + integration tests

---

## 2. Dependencies

Add `pdfplumber` to `requirements.txt`:

```
google-api-python-client
google-auth-httplib2
google-auth-oauthlib
pdfplumber
```

All other dependencies (`sqlite3`, `dataclasses`, `re`, `datetime`, `pathlib`, `logging`, `argparse`) are in the Python standard library.

Run: `pip install -r requirements.txt`

---

## 3. Data Model — `src/smtc_handicap/models.py`

Three dataclasses, no methods — pure data containers.

### 3.1 Race

```python
@dataclass
class Race:
    race_id: str           # "STAGNI_CUP_2026-01-21" or "PRACTICE_TOP_2026-01-21"
    name: str              # "THE STAGNI CUP" or "PRACTICE"
    date: datetime.date
    start_position: str    # "TOP" | "JUNCTION"
    is_handicap_race: bool
    is_practice: bool
    day_number: int | None = None   # multi-day races: 1, 2, etc.
    pdf_source: str = ""            # original PDF filename
```

**race_id generation rules:**
- Practice: `PRACTICE_{TOP|JUNCTION}_{YYYY-MM-DD}`
- Named race: `{RACE_NAME_SLUG}_{YYYY-MM-DD}` (strip "THE ", replace spaces with `_`)
- Multi-day race: `{RACE_NAME_SLUG}_DAY{N}_{YYYY-MM-DD}`

### 3.2 Rider

```python
@dataclass
class Rider:
    rider_id: str          # normalized ID from name_normalizer, e.g. "rueda_fp_jnr"
    display_name: str      # as first seen: "F.P. Rueda (Jnr)"
    nationality: str = ""  # "GB", "CH", "USA", etc.
    is_sl: bool = False    # Supplementary List
    is_am: bool = False    # Amateur "(AM)"
    first_seen_date: datetime.date = field(
        default_factory=lambda: datetime.date(2099, 1, 1)  # sentinel: any real date replaces it
    )
```

### 3.3 TimeRecord

```python
@dataclass
class TimeRecord:
    record_id: str         # "{race_id}_{rider_id}_{run_number}"
    race_id: str           # FK → Race
    rider_id: str          # FK → Rider
    run_number: int        # 1-based
    # Splits (populated from Split Results section)
    start_time: datetime.time | None = None   # clock time, e.g. 09:34:56
    split_junction: float | None = None       # seconds (0.0 if started from Junction)
    split_rise: float | None = None
    split_stream: float | None = None
    split_bulpetts: float | None = None
    finish_time: float | None = None          # total seconds; None if fall/DNF
    speed_mph: float | None = None
    # Handicap
    handicap: float | None = None  # 0.0 = scratch, None = non-handicap race
    # Status
    is_fall: bool = False
    fall_location: str | None = None  # "S", "TH", "JS", "CH", "BA", "ST"
    is_dnf: bool = False
```

---

## 4. SQLite Schema — `src/smtc_handicap/db.py`

### 4.1 CREATE TABLE statements

```sql
CREATE TABLE IF NOT EXISTS riders (
    rider_id        TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    nationality     TEXT NOT NULL DEFAULT '',
    is_sl           INTEGER NOT NULL DEFAULT 0,
    is_am           INTEGER NOT NULL DEFAULT 0,
    first_seen_date TEXT NOT NULL               -- ISO "YYYY-MM-DD"
);

CREATE TABLE IF NOT EXISTS races (
    race_id          TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    date             TEXT NOT NULL,              -- ISO "YYYY-MM-DD"
    start_position   TEXT NOT NULL CHECK (start_position IN ('TOP', 'JUNCTION')),
    is_handicap_race INTEGER NOT NULL DEFAULT 0,
    is_practice      INTEGER NOT NULL DEFAULT 0,
    day_number       INTEGER,                   -- NULL for single-day/practice
    pdf_source       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS time_records (
    record_id      TEXT PRIMARY KEY,
    race_id        TEXT NOT NULL REFERENCES races(race_id),
    rider_id       TEXT NOT NULL REFERENCES riders(rider_id),
    run_number     INTEGER NOT NULL,
    start_time     TEXT,        -- "HH:MM:SS" or NULL
    split_junction REAL,
    split_rise     REAL,
    split_stream   REAL,
    split_bulpetts REAL,
    finish_time    REAL,        -- seconds, NULL if fall/DNF
    speed_mph      REAL,
    handicap       REAL,        -- NULL for non-handicap races
    is_fall        INTEGER NOT NULL DEFAULT 0,
    fall_location  TEXT,
    is_dnf         INTEGER NOT NULL DEFAULT 0,
    UNIQUE(race_id, rider_id, run_number)
);
```

### 4.2 Indexes

```sql
CREATE INDEX IF NOT EXISTS idx_time_records_rider ON time_records(rider_id);
CREATE INDEX IF NOT EXISTS idx_time_records_race  ON time_records(race_id);
CREATE INDEX IF NOT EXISTS idx_races_date         ON races(date);
CREATE INDEX IF NOT EXISTS idx_races_position     ON races(start_position);
CREATE INDEX IF NOT EXISTS idx_time_records_rider_race ON time_records(rider_id, race_id);
```

### 4.3 Database class — `CrestaDB`

```python
class CrestaDB:
    def __init__(self, db_path: str | Path) -> None:
        # Opens/creates DB, sets PRAGMA journal_mode=WAL, foreign_keys=ON
        # Calls _create_tables()

    def _create_tables(self) -> None: ...

    # -- Rider --
    def upsert_rider(self, rider: Rider) -> None: ...
    def get_rider(self, rider_id: str) -> Rider | None: ...
    def get_all_riders(self) -> list[Rider]: ...

    # -- Race --
    def insert_race(self, race: Race) -> None: ...       # INSERT OR IGNORE
    def get_race(self, race_id: str) -> Race | None: ...
    def race_exists(self, race_id: str) -> bool: ...

    # -- TimeRecord --
    def insert_time_record(self, record: TimeRecord) -> None: ...  # INSERT OR IGNORE
    def get_time_records_for_rider(self, rider_id, start_position=None) -> list[TimeRecord]: ...
    def get_time_records_for_race(self, race_id: str) -> list[TimeRecord]: ...

    # -- Lifecycle --
    def close(self) -> None: ...
    def __enter__(self) -> CrestaDB: ...
    def __exit__(self, *args) -> None: ...
```

**Rider upsert merge rules** (most important logic):
- `display_name`: keep existing (first-seen is canonical)
- `nationality`: update only if existing is empty and new is non-empty
- `is_sl` / `is_am`: OR logic (True if either is True)
- `first_seen_date`: keep the earlier of existing and new

Implementation: fetch existing with `get_rider()`, merge in Python, then `UPDATE`. This is clearer than a pure-SQL upsert for readability.

**Race/TimeRecord inserts**: use `INSERT OR IGNORE` — duplicates are silently skipped based on primary key.

---

## 5. Rider Name Normalization — `src/smtc_handicap/name_normalizer.py`

Single public function: `normalize_rider_id(display_name: str) -> str`

### Algorithm (step by step):

```
Input: "The Hon M.V.O. de C. Wrottesley"

Step 1 — Remove titles (ordered longest-first):
  Titles: "The Rt Hon", "The Hon", "Lt-Cdr", "Lt Cdr", "Maj-Gen",
          "Count", "Lord", "Sir", "Dr", "Prof"
  Result: "M.V.O. de C. Wrottesley"

Step 2 — Remove markers:
  Strip "(AM)", "(SL)", "**" from string
  Result: "M.V.O. de C. Wrottesley"  (no change here)

Step 3 — Extract parenthetical qualifiers:
  Regex: \((\w+)\) → captures "Jnr", "Snr", etc.
  Remove from string, save as qualifier (lowercased)
  Result: "M.V.O. de C. Wrottesley", qualifier = None

Step 4 — Tokenize on whitespace:
  ["M.V.O.", "de", "C.", "Wrottesley"]

Step 5 — Classify each token:
  - Initials: matches ^([A-Za-z]\.)+$ → "M.V.O." → "mvo", "C." → "c"
  - Particles: in {"de","di","da","von","van","du","le","la","del"} → "de"
  - Surname: everything else → "Wrottesley"

Step 6 — Identify surname:
  Walk tokens RIGHT to LEFT. First token that is NOT an initial and NOT
  a particle is the surname. Here: "Wrottesley"

Step 7 — Build ID:
  [surname] + [all non-surname tokens in original left-to-right order] + [qualifier]
  "wrottesley" + "mvo" + "de" + "c" = "wrottesley_mvo_de_c"

Step 8 — Cleanup:
  Hyphens → underscores. Collapse multiple underscores. Strip trailing.
```

### Expected outputs:

| Input | Output |
|-------|--------|
| `F.P. Rueda (Jnr)` | `rueda_fp_jnr` |
| `The Hon M.V.O. de C. Wrottesley` | `wrottesley_mvo_de_c` |
| `Count F. Guerrini-Maraldi` | `guerrini_maraldi_f` |
| `Lord Doune` | `doune` |
| `B.A.P. Bracher` | `bracher_bap` |
| `Lt-Cdr J.R. Smith` | `smith_jr` |
| `C.E. Wallace` | `wallace_ce` |

Raise `ValueError` if name is empty after cleanup.

---

## 6. PDF Filename Parser — `src/smtc_handicap/filename_parser.py`

Single public function: `parse_pdf_filename(filename: str) -> dict`

### Filename format: `YYYYMMDD [components] + [components].pdf`

Components detected via word-boundary regex (`\brt\b`, `\bpt\b`, etc.):

| Component | Meaning |
|-----------|---------|
| `rt` | Race from Top |
| `rj` | Race from Junction |
| `pt` | Practice from Top |
| `pj` | Practice from Junction |
| `splits` | Split timing data included |
| `(Name)` | Race name in parentheses |
| `Day One/Two/...` | Multi-day race day number (inside parentheses) |

### Return dict:

```python
{
    "date": "2026-01-21",           # str, ISO format
    "has_race_top": True,
    "has_race_junction": False,
    "has_practice_top": True,
    "has_practice_junction": True,
    "has_splits": True,
    "race_name": "Stagni Cup",      # str or None
    "day_number": None,             # int or None
    "original_filename": "20260121 rt (Stagni Cup) + pt + pj + splits.pdf"
}
```

**Day number extraction**: If `race_name` contains "Day One/Two/Three/...", extract the number and strip it from the race name.

---

## 7. PDF Parser — `src/smtc_handicap/pdf_parser.py`

This is the most complex module. It uses `pdfplumber` to extract text, detects sections by header patterns, and dispatches to sub-parsers.

### 7.1 Top-level entry point

```python
def parse_pdf(filepath: Path) -> ParsedPDF:
    # 1. Parse filename metadata (date, components)
    # 2. Extract all text lines from all pages (pdfplumber)
    # 3. Detect sections (headers → typed Section objects)
    # 4. Parse each section → Race, Rider, TimeRecord objects
    # 5. Return ParsedPDF container

@dataclass
class ParsedPDF:
    filename: str
    races: list[Race]
    riders: list[Rider]
    time_records: list[TimeRecord]
    warnings: list[str]          # parsing anomalies for debugging
```

### 7.2 Text extraction

```python
def extract_all_text_lines(filepath: Path) -> list[str]:
    """Use pdfplumber to get all text lines, filtering out:
    - Empty lines
    - Page break markers matching regex: ^-\s*\d+\s*-$  (e.g. "- 2 -")
    """
```

### 7.3 Section detection

Each PDF has multiple sections. Detect them by scanning for header patterns:

| Section Type | Detection Pattern |
|---|---|
| **Practice** | Line matches `^PRACTICE\s*-\s*(TOP\|JUNCTION)$` |
| **Race (Handicap)** | Line matches a race name pattern (e.g. `THE STAGNI CUP`) AND the first few data lines contain `H'Cap` |
| **Race (Non-Handicap)** | Same race name pattern but NO `H'Cap` column |
| **Split Results** | Line matches `^Split\s+Results?$` |
| **Metadata** | Line contains "Fastest Time" or "Fastest Speed" (skip these) |

Race name regex:
```python
RE_RACE_HEADER = re.compile(
    r"^(?:THE\s+)?([A-Z][A-Z\s']+(?:CUP|TROPHY|PLATE|PRIZE|CHALLENGE|SHIELD|RACE))"
    r"(?:\s*-?\s*DAY\s+(ONE|TWO|THREE|1|2|3))?$",
    re.IGNORECASE,
)
```

```python
@dataclass
class Section:
    section_type: str   # "RACE_HANDICAP" | "RACE_NON_HANDICAP" | "PRACTICE" | "SPLIT" | "METADATA"
    header_line: str
    start_position: str # "TOP" or "JUNCTION"
    race_name: str
    day_number: int | None
    lines: list[str]    # all text lines belonging to this section

def detect_sections(lines: list[str], filename_metadata: dict) -> list[Section]:
    """Walk lines top-to-bottom. When a header pattern matches, start a new
    Section. All subsequent lines belong to it until the next header."""
```

**Determining start_position for race sections**: Use filename metadata — if `has_race_top` is True, race section is "TOP"; if `has_race_junction`, it's "JUNCTION".

### 7.4 Column splitting strategy

PDF text lines have variable whitespace. Names contain single spaces; columns are separated by 2+ spaces.

```python
def split_row_into_columns(line: str) -> list[str]:
    """Split on 2+ whitespace chars. Keeps names intact."""
    return re.split(r'\s{2,}', line.strip())
```

### 7.5 Time cell parser

Handles the various formats found in time columns:

```python
RE_FALL = re.compile(r"Fall\(([A-Z]+)\)", re.IGNORECASE)
RE_TIME_VALUE = re.compile(r"^\d+\.\d+$")

def parse_time_cell(cell: str) -> tuple[float | None, bool, str | None]:
    """
    "51.67"    → (51.67, False, None)
    "Fall(S)"  → (None,  True,  "S")
    "Fall(TH)" → (None,  True,  "TH")
    "DNF"      → (None,  False, None)   # set is_dnf separately
    ""  / "-"  → (None,  False, None)
    """
```

### 7.6 Sub-parsers (one per section type)

#### Practice parser

```python
def parse_practice_section(section, race_date, pdf_source) -> tuple[Race, list[Rider], list[TimeRecord]]:
```

**Row format**: `Name    Nat    Time1    Time2    Time3`

Row parsing regex: `^(.+?)\s{2,}([A-Z]{2,3})\s{2,}(.+)$`
- Group 1 = rider name (check for `(AM)`, `(SL)`, `**` markers)
- Group 2 = nationality code
- Group 3 = space-separated time values → parse each with `parse_time_cell()`

**For each time value**, create a `TimeRecord` with `run_number` = 1, 2, 3...

**Race ID**: `PRACTICE_{TOP|JUNCTION}_{YYYY-MM-DD}`

#### Handicap race parser

```python
def parse_race_handicap_section(section, race_date, pdf_source) -> tuple[Race, list[Rider], list[TimeRecord]]:
```

**Row format**: `Rank    Name    H'Cap    1st    2nd    3rd    Total    Net Total`

Parsing steps:
1. Find header row (contains `H'Cap`)
2. For each data row, `split_row_into_columns()`:
   - Column 0: rank (may start with `=` for ties) — not stored, just skip
   - Column 1: rider name
   - Column 2: handicap value — `"Scr"` / `"SCR"` → 0.0, else `float(value)`
   - Columns 3..N-2: run times → `parse_time_cell()`
   - Column N-1: Total (skip — computed value)
   - Column N: Net Total (skip — computed value, but use for validation)

**Validation**: `net_total ≈ sum(run_times) - handicap × num_runs`. Log warning if mismatch.

#### Non-handicap race parser

Same as handicap but:
- No H'Cap column → `handicap = None` on all TimeRecords
- No Net Total column
- Column layout: `[Rank] [Name] [1st] [2nd] [...] [Total]`

#### Split results parser

```python
def parse_split_section(section, race_date, existing_records) -> list[TimeRecord]:
```

**Row format**: `Name    Start    Junction    Rise    Stream    Bulpetts    Finish    MPH`

This section **merges into existing TimeRecords** (already parsed from race/practice sections):
1. Parse each row: extract rider_id, start_time (`HH:MM:SS` → `datetime.time`), split floats, finish float, speed float
2. Match to existing TimeRecord by `(rider_id, finish_time)` — both must match
3. If no finish_time match (fall), match by sequential order (Nth split row = Nth run)
4. Update the matched TimeRecord's split fields and speed_mph

### 7.7 Parsing edge cases checklist

| Edge Case | How to Handle |
|---|---|
| `Fall(S)`, `Fall(TH)` | `parse_time_cell()` → `is_fall=True`, `fall_location="S"`, `finish_time=None` |
| `Scr` / `SCR` | Handicap = 0.0 (scratch rider) |
| `**` next to name | Rider is "riding not racing" — still store run, but flag via a warning |
| `(AM)` in name | Strip from name, set `is_am=True` on Rider |
| `(SL)` in name | Strip from name, set `is_sl=True` on Rider |
| `=2` rank | Tied rank — ignore rank column entirely (not stored) |
| `- 2 -` page break | Filtered out during text extraction |
| Empty line / dashes line | Skip during row parsing |
| Multi-page tables | Handled by extracting ALL pages first, then detecting sections across the full text |

---

## 8. Pipeline Orchestrator — `src/smtc_handicap/pipeline.py`

```python
@dataclass
class IngestStats:
    pdfs_processed: int = 0
    pdfs_failed: int = 0
    races_inserted: int = 0
    riders_upserted: int = 0
    time_records_inserted: int = 0
    warnings: list[str] = field(default_factory=list)

def ingest_single_pdf(db: CrestaDB, filepath: Path) -> IngestStats:
    """Parse one PDF and store in DB.
    Order: upsert riders first → insert races → insert time_records (FK deps)."""

def ingest_all_pdfs(pdf_dir: Path, db_path: Path) -> IngestStats:
    """Process all *.pdf files in pdf_dir sorted by name (date order).
    Accumulate and return aggregate stats."""
```

### CLI scripts

**`scripts/ingest_pdfs.py`**: Argparse CLI wrapping `ingest_all_pdfs()`.
- `--pdf-dir` (default: `data/raw_pdfs`)
- `--db` (default: `data/cresta.db`)
- `--verbose` / `-v` for debug logging
- Prints summary stats on completion

**`scripts/inspect_db.py`**: Quick DB inspection tool.
- `--counts` (default): show row counts per table
- `--riders`: list all riders
- `--races`: list all races
- `--records --rider <id>`: list time records for a specific rider

---

## 9. Testing Strategy

### Unit tests (no PDF files needed)

| Test File | What's Tested | Approx Cases |
|---|---|---|
| `test_name_normalizer.py` | 10+ parametrized name→ID mappings, empty name error | ~12 |
| `test_filename_parser.py` | Practice-only, race+practice, multi-day, junction filenames | ~5 |
| `test_models.py` | Dataclass defaults, construction, required fields | ~5 |
| `test_db.py` | Insert/upsert/get for all 3 tables, duplicate handling, FK constraints, upsert merge logic | ~10 |
| `test_pdf_parser.py` | `parse_time_cell()`, `split_row_into_columns()`, section detection with synthetic text | ~10 |

### Integration tests (require real PDFs in `tests/fixtures/`)

Mark with `@pytest.mark.integration`. Skip if fixture files not present.
- Parse a real multi-section PDF, verify non-zero counts of races/riders/records
- Full pipeline: ingest 1 PDF into in-memory DB, verify data integrity

### Shared fixtures in `tests/conftest.py`

- `in_memory_db` — fresh `:memory:` CrestaDB for each test
- `sample_rider`, `sample_race`, `sample_time_record` — reusable dataclass instances

### pytest config

Add to `pyproject.toml` under `[tool.pytest.ini_options]`:
```toml
markers = ["integration: tests requiring real PDF files in tests/fixtures/"]
```

---

## 10. Verification Steps

### Step 1: Run unit tests
```bash
pip install -r requirements.txt
pytest --verbose -m "not integration"
```

### Step 2: Test with 1 real PDF
```bash
# Place one PDF in data/raw_pdfs/
python scripts/ingest_pdfs.py --verbose
python scripts/inspect_db.py --counts
```

### Step 3: Validate data integrity via SQL
```sql
-- Orphan time_records (should return 0 rows each)
SELECT tr.record_id FROM time_records tr LEFT JOIN riders r ON tr.rider_id = r.rider_id WHERE r.rider_id IS NULL;
SELECT tr.record_id FROM time_records tr LEFT JOIN races ra ON tr.race_id = ra.race_id WHERE ra.race_id IS NULL;

-- Handicap races should have non-null handicap values
SELECT record_id FROM time_records tr JOIN races r ON tr.race_id = r.race_id WHERE r.is_handicap_race = 1 AND tr.handicap IS NULL;

-- Falls should have no finish_time
SELECT record_id FROM time_records WHERE is_fall = 1 AND finish_time IS NOT NULL;
```

### Step 4: Manual spot-check
Pick one rider from the PDF, visually verify their times in the DB match the PDF exactly.

### Step 5: Full ingestion
```bash
python scripts/ingest_pdfs.py --verbose 2>&1 | tee data/ingest_log.txt
python scripts/inspect_db.py --counts
```
Target: 90%+ of PDFs parsed successfully (per PRD success criteria).

---

## Implementation Order Summary

| # | File | Depends On |
|---|------|-----------|
| 1 | Update `requirements.txt` | — |
| 2 | `src/smtc_handicap/models.py` + `tests/test_models.py` | — |
| 3 | `src/smtc_handicap/name_normalizer.py` + `tests/test_name_normalizer.py` | — |
| 4 | `src/smtc_handicap/filename_parser.py` + `tests/test_filename_parser.py` | — |
| 5 | `src/smtc_handicap/db.py` + `tests/test_db.py` | models.py |
| 6 | `src/smtc_handicap/pdf_parser.py` + `tests/test_pdf_parser.py` | models.py, name_normalizer.py |
| 7 | `src/smtc_handicap/pipeline.py` + scripts + `tests/conftest.py` | all above |
| 8 | Integration test with real PDF + verification | all above |
