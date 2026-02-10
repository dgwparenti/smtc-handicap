# Cresta Run Handicapping System - PRD v0.2

## Problem Statement
Manual handicapping for Cresta Run races relies on committee judgment, which is time-consuming and inconsistent. This system will use Bayesian statistics to generate fair handicaps that bring all riders within a few hundredths/tenths of a second of competitive parity.

---

## Key Terminology
- **Top**: Starting position at the top of the course (~51-80+ second runs)
- **Junction**: Starting position partway down (~44-55+ second runs)  
- **Raw Time**: Actual recorded finish time
- **Handicap (H'Cap)**: Time deducted from raw time in handicap races (e.g., "Scr" = scratch = 0)
- **Net Total**: Sum of (raw times - handicap × number of runs) used for standings
- **Fall(XX)**: Rider fell at location XX (e.g., Fall(S) = Shuttlecock, Fall(TH) = Top House)
- **SL**: Supplementary List rider (less experienced)
- **Split Times**: Intermediate timing points (Junction, Rise, Stream, Bulpetts, Finish)

---

## Data Sources

### Email → Link → PDF Pipeline
```
Gmail Inbox
    │
    ▼ (search by subject/sender pattern)
Daily Results emails (Mailchimp format)
    │
    ▼ (parse HTML, extract href from "click here" links)
Direct PDF URLs (or results page URLs)
    │
    ▼ (download PDF)
Local PDF files in data/raw_pdfs/
    │
    ▼ (parse with pdfplumber)
Structured data in SQLite
```

### Email Format Details (Mailchimp)
| Field | Pattern |
|-------|---------|
| **Subject** | `"{Weekday} {Date} - Daily Results"` |
| **Example** | `"Friday 30th January 2026 - Daily Results"` |
| **Senders** | `*@cresta-run.com` (multiple secretaries rotate) |
| **Known senders** | `tilly.macdonald@cresta-run.com`, `annabel.kettler@cresta-run.com` |
| **Results link text** | "For Today's results please click here" or similar variants |
| **Draw link text** | "Tomorrow's draw awaits you here" or "For the Draw, please click here" |
| **Email format** | HTML (Mailchimp template) |

### Link Extraction Strategy
The "click here" text contains an `<a href="...">` tag. Extract the URL from:
```html
For Today's results please <a href="https://...">click here</a>.
```

**Important**: The link may go directly to a PDF, or to an intermediate page. Need to handle both cases.

---

## Data Model

### Race Record
```python
@dataclass
class Race:
    race_id: str           # "{race_name}_{date}" e.g., "STAGNI_CUP_2026-01-21"
    name: str              # "THE STAGNI CUP", "PRACTICE", "THE BRABAZON TROPHY"
    date: date             # Race date
    start_position: str    # "TOP" | "JUNCTION"
    is_handicap_race: bool # True if handicap column present
    is_practice: bool      # True if "PRACTICE" in name
    day_number: int | None # For multi-day races: 1, 2, etc.
    pdf_source: str        # Original PDF filename/path
```

### Time Record
```python
@dataclass
class TimeRecord:
    record_id: str         # "{race_id}_{rider_id}_{run_number}"
    race_id: str           # FK to Race
    rider_id: str          # FK to Rider
    run_number: int        # 1, 2, 3... (order of runs that day)
    
    # Timing data (all in seconds)
    start_time: time | None      # e.g., 09:34:56 (from split results)
    split_junction: float | None # Split time at Junction (0.00 if started from Junction)
    split_rise: float | None     # Split time at Rise  
    split_stream: float | None   # Split time at Stream
    split_bulpetts: float | None # Split time at Bulpetts
    finish_time: float | None    # Final time in seconds
    speed_mph: float | None      # Speed at finish
    
    # Handicap data (only for handicap races)
    handicap: float | None       # Handicap applied (0 = scratch, None = non-handicap race)
    
    # Status
    is_fall: bool                # True if rider fell
    fall_location: str | None    # "S", "TH", "JS", "CH", "BA", "ST" etc.
    is_dnf: bool                 # Did not finish for other reasons
```

**Note on Splits**: Split times are recorded for ALL runs (practice and races). The split results section at the end of each PDF contains the detailed timing for every run, including practice runs. This data is valuable for:
- Analyzing rider technique (where do they gain/lose time?)
- Detecting consistency issues at specific track sections
- More granular performance modeling

### Rider Record
```python
@dataclass  
class Rider:
    rider_id: str          # Normalized unique ID (generated from name)
    display_name: str      # As shown on results: "F.P. Rueda (Jnr)"
    nationality: str       # "GB", "CH", "USA", "ZA", etc.
    is_sl: bool           # Supplementary List rider (less experienced)
    is_am: bool           # Amateur marker "(AM)"
    first_seen_date: date  # For tracking improvement over time
    
    # Computed fields (calculated from TimeRecords, not stored)
    # fastest_ever_top: float
    # fastest_ever_junction: float
    # fastest_season_top: float
    # fastest_season_junction: float
    # average_season_top: float
    # average_season_junction: float
    # current_handicap_top: float
    # current_handicap_junction: float
```

### Example Parsed Data

**From Stagni Cup (Handicap Race):**
```
Race: STAGNI_CUP_2026-01-21, TOP, handicap=True

TimeRecord:
  rider: "C.E. Wallace"
  handicap: 3.00
  run_1: 57.39, run_2: 56.53, run_3: 55.87
  net_total: 160.79  # (57.39-3) + (56.53-3) + (55.87-3) = 160.79
  
TimeRecord:
  rider: "F.J.A. Hitz"  
  handicap: 0.00 (Scr = Scratch)
  run_1: 53.42, run_2: 55.13, run_3: 53.97
  net_total: 162.52
```

**From Practice (Non-Handicap):**
```
Race: PRACTICE_TOP_2026-02-10

TimeRecord:
  rider: "F.P. Rueda (Jnr)"
  run_1: 51.67 (no run_2 recorded)
  
TimeRecord:
  rider: "B.A.P. Bracher"
  run_1: 91.57, run_2: 76.68
```

---

## Gmail Integration Specification

### Gmail Filter Configuration
```yaml
gmail_filter:
  # Subject pattern: "{Weekday} {Date} - Daily Results"
  subject_patterns:
    - "*Daily Results*"
  
  # Multiple secretaries send results
  allowed_senders:
    - "tilly.macdonald@cresta-run.com"
    - "annabel.kettler@cresta-run.com"
    # Or use wildcard matching on domain
  
  sender_domain: "cresta-run.com"  # Alternative: match any sender from this domain
  
  after_date: "2020-01-01"  # Adjust based on available history
  
  # PDFs are behind links, not attachments
  require_pdf_attachment: false
```

### PDF URL Format (Mailchimp → Webflow CDN)

**Email contains Mailchimp tracking links** that redirect to the actual PDF:

```
Step 1 - URL in email (Mailchimp tracker):
https://cresta-run.us18.list-manage.com/track/click?u=84565b3a39b695f056cc58618&id=01b570f1d9&e=f0da7ca379

Step 2 - After redirect (Webflow CDN):
https://cdn.prod.website-files.com/6683b5e9996939074972a682/69736fc8a00653a090a5668e_20260123%20pt%20%2B%20pj%20%2B%20splits.pdf
```

**Handling redirects:**
```python
import requests

def download_pdf_from_email_link(mailchimp_url: str) -> tuple[bytes, str]:
    """
    Download PDF following Mailchimp redirect.
    
    Returns: (pdf_bytes, final_url)
    """
    response = requests.get(mailchimp_url, allow_redirects=True)
    response.raise_for_status()
    
    # response.url contains the final URL after redirects
    final_url = response.url
    
    return response.content, final_url
```

**Final URL filename encoding** (URL-decoded):
| Filename | Content |
|----------|---------|
| `20260123 pt + pj + splits.pdf` | Practice Top + Practice Junction + Splits |
| `20260121 rt (Stagni Cup) + pt + pj + splits.pdf` | Race Top + Practice + Splits |
| `20260207 rt (Brabazon Trophy Day One) + pt + pj + Splits.pdf` | Multi-day Race + Practice + Splits |

**Filename components:**
- `YYYYMMDD` - Date
- `rt` - Race Top
- `rj` - Race Junction  
- `pt` - Practice Top
- `pj` - Practice Junction
- `(Race Name)` - Name of race/cup in parentheses
- `splits` - Split times included

### Link Extraction Logic
```python
from bs4 import BeautifulSoup
from urllib.parse import urlparse, unquote
import re

def extract_results_link(html_body: str) -> str | None:
    """
    Extract the results PDF link from a Daily Results email.
    
    The link is embedded in text like:
    - "For Today's results please click here"
    - "For today's results, please click here"
    
    Returns direct Webflow CDN URL to PDF.
    """
    soup = BeautifulSoup(html_body, 'html.parser')
    
    # Find all links
    for link in soup.find_all('a', href=True):
        href = link['href']
        link_text = link.get_text().lower()
        parent_text = link.parent.get_text().lower() if link.parent else ""
        
        # Method 1: Check if it's a direct PDF link to Webflow CDN
        if 'cdn.prod.website-files.com' in href and href.endswith('.pdf'):
            # Verify it's results, not draw
            if 'draw' not in unquote(href).lower():
                return href
        
        # Method 2: Check link context
        if 'click here' in link_text or link_text == 'here':
            if 'result' in parent_text and 'draw' not in parent_text:
                return href
    
    return None

def parse_pdf_filename(url: str) -> dict:
    """
    Parse metadata from PDF URL filename.
    
    Example: '20260121 rt (Stagni Cup) + pt + pj + splits.pdf'
    Returns: {
        'date': '2026-01-21',
        'has_race_top': True,
        'has_race_junction': False,
        'has_practice_top': True,
        'has_practice_junction': True,
        'has_splits': True,
        'race_name': 'Stagni Cup'
    }
    """
    # Decode URL and extract filename
    decoded = unquote(url)
    filename = decoded.split('_')[-1]  # Get part after file ID
    filename_lower = filename.lower()
    
    # Extract date (YYYYMMDD at start)
    date_match = re.search(r'(\d{8})', filename)
    date_str = date_match.group(1) if date_match else None
    
    # Extract race name if present
    race_match = re.search(r'\(([^)]+)\)', filename)
    race_name = race_match.group(1) if race_match else None
    
    return {
        'date': f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}" if date_str else None,
        'has_race_top': ' rt ' in filename_lower or filename_lower.startswith('rt '),
        'has_race_junction': ' rj ' in filename_lower,
        'has_practice_top': ' pt ' in filename_lower,
        'has_practice_junction': ' pj ' in filename_lower,
        'has_splits': 'split' in filename_lower,
        'race_name': race_name,
        'original_filename': filename
    }
```

---

## PDF Parsing Specification

### Document Structure Detection
Each PDF contains multiple sections that must be parsed differently:

| Section Type | Identifier | Parse Strategy |
|--------------|------------|----------------|
| Race Results (Handicap) | "H'Cap" column header | Extract rank, name, handicap, run times, total |
| Race Results (Non-Handicap) | No H'Cap, has "1st", "2nd" columns | Extract rank, name, run times, total |
| Practice Results | "PRACTICE - TOP/JUNCTION" | Extract name, nationality, time columns |
| Split Results | "Split Results" header | Extract name, start time, all splits, finish, speed |
| Metadata | "Fastest Time", "Fastest Speed" | Extract records |

### Parsing Challenges
1. **Variable columns**: Practice has 1-3 time columns, races have 3+ runs
2. **Fall notation**: "Fall(S)" must be parsed, not treated as numeric
3. **Tied rankings**: "=2" indicates tie
4. **Special markers**: "Scr" = 0 handicap, "**" = riding but not racing, "(AM)" = amateur
5. **Multi-page**: Results continue across pages with "- 2 -" markers
6. **Name variations**: Same rider may appear as "F.P. Rueda (Jnr)" or "RUEDA F.P. (JNR)"

### Rider Name Normalization
```python
def normalize_rider_id(name: str) -> str:
    """
    'F.P. Rueda (Jnr)' -> 'rueda_fp_jnr'
    'The Hon M.V.O. de C. Wrottesley' -> 'wrottesley_mvo_de_c'
    'Count F. Guerrini-Maraldi' -> 'guerrini_maraldi_f'
    """
    # Remove titles: "The Hon", "Count", "Lord", "Lt-Cdr"
    # Extract surname (last word before markers)
    # Extract initials
    # Normalize to lowercase with underscores
```

---

## Bayesian Model Design

### Model Per Rider Per Start Position
Since TOP and JUNCTION have different time ranges, model separately:

```python
# For each rider, for each start position (TOP/JUNCTION):

# Prior: Informed by population
μ_population = mean(all_rider_times)  # ~57s for TOP, ~48s for JUNCTION
σ_population = std(all_rider_times)   # ~5-10s

# Likelihood: Rider's observed times
rider_times ~ Normal(μ_rider, σ_rider)

# Posterior: Updated belief about rider's true ability
μ_rider | data ~ Normal(μ_posterior, σ_posterior)
```

### Handicap Calculation
**Target**: All riders should have equal probability of winning

```python
def calculate_handicap(rider_id: str, field: list[str], start_position: str) -> float:
    """
    Calculate handicap such that rider has ~equal chance of winning.
    
    Approach:
    1. Get posterior distribution for each rider in field
    2. Find fastest expected time (usually scratch rider)
    3. Handicap = rider_expected - scratch_expected
    
    Refinement:
    - Weight recent performances higher
    - Account for rider consistency (high σ = risky)
    - Consider conditions (though not in current data)
    """
    scratch_time = min(get_expected_time(r, start_position) for r in field)
    rider_time = get_expected_time(rider_id, start_position)
    return rider_time - scratch_time
```

### Key Metrics for Committee
```python
@dataclass
class RiderHandicapReport:
    rider_id: str
    start_position: str  # TOP or JUNCTION
    
    # Historical
    fastest_ever: float
    fastest_this_season: float
    season_average: float
    num_runs_this_season: int
    
    # Bayesian estimates
    expected_time: float       # μ_posterior
    uncertainty: float         # σ_posterior (95% CI width)
    consistency: float         # σ_rider (lower = more consistent)
    
    # Recommendation
    suggested_handicap: float
    confidence: str            # "HIGH" | "MEDIUM" | "LOW"
```

---

## MVP Scope

### Phase 1: Data Pipeline (Week 1-2)
- [ ] Gmail authentication and email search
- [ ] Link extraction from email bodies
- [ ] PDF download from result pages
- [ ] PDF text extraction (pdfplumber)
- [ ] Basic section detection (Practice vs Race vs Splits)

### Phase 2: Parsing Engine (Week 2-3)
- [ ] Practice results parser
- [ ] Race results parser (with handicap)
- [ ] Split results parser
- [ ] Rider name normalization
- [ ] Data validation and deduplication

### Phase 3: Data Storage (Week 3)
- [ ] SQLite database schema
- [ ] Import historical data
- [ ] Query interface for analysis

### Phase 4: Bayesian Model (Week 4)
- [ ] Basic Normal model per rider
- [ ] Handicap calculation logic
- [ ] Season/career statistics
- [ ] Export handicap recommendations

### Phase 5: Reporting (Week 5)
- [ ] Excel export of handicap sheet
- [ ] Rider performance summaries
- [ ] Comparison with committee handicaps

---

## Technical Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Gmail Account                          │
└─────────────────────┬───────────────────────────────────────┘
                      │ Gmail API
                      ▼
┌─────────────────────────────────────────────────────────────┐
│               gmail_extractor.py                            │
│  • Search emails by subject/sender                          │
│  • Extract links from email bodies                          │
│  • Follow links to results pages                            │
│  • Download PDFs                                            │
└─────────────────────┬───────────────────────────────────────┘
                      │ PDF files
                      ▼
┌─────────────────────────────────────────────────────────────┐
│               pdf_parser.py                                 │
│  • Detect document sections                                 │
│  • Parse practice/race/split results                        │
│  • Normalize rider names                                    │
│  • Handle falls, DNFs, special markers                      │
└─────────────────────┬───────────────────────────────────────┘
                      │ Structured data
                      ▼
┌─────────────────────────────────────────────────────────────┐
│               data_store.py (SQLite)                        │
│  • races, time_records, riders tables                       │
│  • Query interface                                          │
│  • Season/career aggregations                               │
└─────────────────────┬───────────────────────────────────────┘
                      │ Historical data
                      ▼
┌─────────────────────────────────────────────────────────────┐
│               bayesian_model.py (PyMC)                      │
│  • Fit rider ability distributions                          │
│  • Generate handicap recommendations                        │
│  • Uncertainty quantification                               │
└─────────────────────┬───────────────────────────────────────┘
                      │ Recommendations
                      ▼
┌─────────────────────────────────────────────────────────────┐
│               Output: Excel / CSV                           │
│  • Handicap sheet for committee                             │
│  • Rider reports                                            │
│  • Historical analysis                                      │
└─────────────────────────────────────────────────────────────┘
```

---

## Open Questions

### All Confirmed ✓
1. ✓ **Email format**: Daily Results from `*@cresta-run.com`, subject pattern `"{Day} {Date} - Daily Results"`
2. ✓ **Link extraction**: HTML email with "click here" hyperlinks (Mailchimp tracking URLs)
3. ✓ **Splits for practice**: Yes, split results are included for all runs (practice and races)
4. ✓ **Net Total formula**: `Σ(raw_time) - (handicap × num_runs)` confirmed
5. ✓ **PDF hosting**: Mailchimp redirect → Webflow CDN (`cdn.prod.website-files.com`)
6. ✓ **Filename contains metadata**: Date, content type (rt/rj/pt/pj), race name, splits indicator
7. ✓ **TOP and JUNCTION handicaps are independent**: A rider can have different handicaps for each start position, but cannot race both in the same event
8. ✓ **Multi-day races**: Sum totals across days
9. ✓ **SL riders**: Should be modeled differently - more variance expected, more room for improvement ride-over-ride
10. ✓ **Historical data**: Emails available from 2021 onwards (~5 seasons, ~60+ days per season = 300+ PDFs)

---

## Business Rules

### Handicap Independence
- TOP and JUNCTION are **separate handicap pools**
- A rider has two independent handicap values: `handicap_top` and `handicap_junction`
- A rider **cannot participate in both** a TOP and JUNCTION handicap race on the same day
- Practice runs from either start position inform that position's model

### Multi-Day Races
- Races like "Brabazon Trophy" span multiple days
- Scoring: Sum of all runs across all days
- Handicap applied per-run, not per-day
- Example: 6 runs over 2 days, handicap × 6 deducted from total

### SL (Supplementary List) Rider Modeling
SL riders require different treatment in the Bayesian model:

| Factor | Regular Member | SL Rider |
|--------|----------------|----------|
| **Prior variance** | Tighter (more history) | Wider (less history) |
| **Improvement rate** | ~0 (stable ability) | Positive (learning curve) |
| **Weighting** | Equal weight all runs | Recent runs weighted higher |
| **Minimum runs for handicap** | 3-5 runs | 5-10 runs (more uncertainty) |

```python
# SL-specific model adjustment
if rider.is_sl:
    # Wider prior - less confident about true ability
    prior_sigma *= 1.5
    
    # Add improvement trend term
    # Expected time decreases with experience
    improvement_rate = pymc.Normal('improvement', mu=-0.5, sigma=0.3)  # seconds per run
    expected_time = base_time + improvement_rate * runs_since_start
```

### Historical Data Volume
- **Seasons**: 2021, 2022, 2023, 2024, 2025, 2026 (current)
- **Estimated PDFs**: ~300+ (60 days × 5 seasons)
- **Runs per rider per season**: Varies, active members may have 50-100+ runs
- **Model confidence**: Strong for regular members, moderate for occasional riders

---

## Success Criteria
1. Successfully parse 90%+ of historical PDFs
2. Rider name matching accuracy >95%
3. Generated handicaps correlate with committee judgments
4. Backtest: Simulated handicap races show improved parity
5. Committee finds recommendations useful and actionable
