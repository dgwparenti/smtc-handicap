"""Build master race reference table from DB and web scrape log."""

import json
import sqlite3
import csv
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT.parent.parent.parent.parent.parent.parent / "data" / "cresta.db"
# Resolve the data path relative to project root
PROJECT_ROOT = ROOT
DATA_DIR = PROJECT_ROOT / "data"

# Canonical race definitions: (race_key, canonical_name, web_title_short, start_position, is_practice, notes)
# start_position: TOP | JUNCTION | BOTH
CANONICAL_RACES = [
    # key, canonical_name, web_short, position, is_practice, notes
    (
        "practice",
        "Practice",
        "PRACTICE",
        "BOTH",
        True,
        "Standard practice session; run from TOP or JUNCTION",
    ),
    (
        "bartley-bear",
        "Bartley Bear",
        "BARTLEY BEAR",
        "BOTH",
        False,
        "Pre-season non-competitive warm-up; both courses",
    ),
    ("university", "University Challenge", "UNIVERSITY", "JUNCTION", False, ""),
    ("nino-bibbia", "Nino Bibbia Challenge Cup", "NINO BIBBIA", "JUNCTION", False, ""),
    ("baron-oertzen", "Baron Oertzen Cup", "BARON OERTZEN", "JUNCTION", False, ""),
    ("bledisloe", "Bledisloe Cup", "BLEDISLOE", "TOP", False, ""),
    ("fairchilds-maccarthy", "Fairchilds MacCarthy", "FAIRCHILDS MacCARTHY", "TOP", False, ""),
    ("heaton", "Heaton Gold Cup", "HEATON", "JUNCTION", False, ""),
    ("lightning", "Lightning Cup", "LIGHTNING", "JUNCTION", False, ""),
    (
        "curzon",
        "Curzon Cup",
        "CURZON DAY 1 / CURZON DAY 2",
        "BOTH",
        False,
        "2-day race; each day run from JUNCTION and TOP simultaneously",
    ),
    ("harjes-cartier", "Harjes Cartier Silver Chip", "HARJES CARTIER", "JUNCTION", False, ""),
    ("escalante", "Escalante Cup", "ESCALANTE", "JUNCTION", False, ""),
    (
        "calisch-grischun",
        "Calisch Grischun",
        "CALISCH GRISCHUN",
        "TOP",
        False,
        "Also run as Junction variant (J) some seasons",
    ),
    ("aris-vatimbella", "Aris Vatimbella Challenge Cup", "ARIS VATIMBELLA", "TOP", False, ""),
    ("swiss", "Swiss Championship", "SWISS", "TOP", False, ""),
    ("knapp", "Knapp Cup", "KNAPP", "TOP", False, ""),
    ("stagni", "Stagni Cup", "STAGNI", "TOP", False, ""),
    ("harland", "Harland Trophy", "HARLAND", "TOP", False, ""),
    (
        "inter-services",
        "Inter Services Championship",
        "INTER SERVICES",
        "TOP",
        False,
        "Army (T) event",
    ),
    ("silver-spoon", "Services' Silver Spoon", "SILVER SPOON", "JUNCTION", False, ""),
    ("morgan", "Morgan Cup", "MORGAN", "TOP", False, "Incorporates Hans Badrutt Challenge Cup"),
    (
        "hans-badrutt",
        "Hans Badrutt Challenge Cup",
        "HANS BADRUTT",
        "TOP",
        False,
        "Held within the Morgan Cup",
    ),
    (
        "brabazon",
        "Brabazon Trophy",
        "BRABAZON DAY 1 / BRABAZON DAY 2",
        "TOP",
        False,
        "2-day race; both days from TOP",
    ),
    ("roger-gibbs", "Roger Gibbs Challenge Cup", "ROGER GIBBS", "JUNCTION", False, ""),
    ("julian-board", "Julian Board Seniors Cup", "JULIAN BOARD", "JUNCTION", False, ""),
    (
        "crawford",
        "Crawford Cup",
        "CRAWFORD",
        "TOP",
        False,
        "Alternates with Marsden Cup some seasons",
    ),
    ("coppa-ditalia", "Coppa d'Italia", "COPPA d'ITALIA", "TOP", False, ""),
    (
        "coppetta",
        "Coppetta d'Italia",
        "COPPETTA",
        "JUNCTION",
        False,
        "Junior version of Coppa d'Italia",
    ),
    ("grand-national", "Grand National", "GRAND NATIONAL", "TOP", False, ""),
    (
        "johannes-badrutt",
        "Johannes Badrutt Memorial Trophy",
        "JOHANNES BADRUTT",
        "TOP",
        False,
        "Was run from JUNCTION in 2024 season",
    ),
    (
        "glattfelder",
        "Glattfelder Cup",
        "GLATTFELDER",
        "JUNCTION",
        False,
        "First run 2022/23 season",
    ),
    (
        "marsden",
        "Marsden Cup",
        "MARSDEN",
        "TOP",
        False,
        "Alternates with Crawford Cup some seasons",
    ),
    ("presidents", "President's Race", "PRESIDENT'S", "JUNCTION", False, ""),
    (
        "gunter-sachs",
        "Gunter Sachs Challenge Cup",
        "GUNTER SACHS",
        "TOP",
        False,
        "Run from JUNCTION in 2019/20; TOP thereafter",
    ),
    (
        "claude-cartier",
        "Claude Cartier Challenge Cup",
        "CLAUDE CARTIER DAY 1 / CLAUDE CARTIER DAY 2",
        "BOTH",
        False,
        "2-day race: Day 1 JUNCTION, Day 2 TOP",
    ),
    ("end-of-term", "End of Term Race", "END OF TERM RACE", "JUNCTION", False, ""),
    ("willoughby", "Willoughby Cup", "WILLOUGHBY", "JUNCTION", False, ""),
    ("ladies", "Ladies' Race", "LADIES", "TOP", False, ""),
    (
        "ladies-grand-national",
        "Ladies Grand National",
        "LADIES GRAND NATIONAL",
        "TOP",
        False,
        "First appeared 2023/24 season",
    ),
    (
        "ladies-services",
        "Ladies' Services Race",
        "LADIES' SERVICES",
        "TOP",
        False,
        "Similar format to Inter Services",
    ),
    ("nigel-moores", "Nigel Moores Memorial Race", "NIGEL MOORES", "JUNCTION", False, ""),
    ("payne-cup", "Payne Cup", "PAYNE CUP", "TOP", False, ""),
    (
        "lorna-robertson",
        "Lorna Robertson Challenge Cup",
        "LORNA ROBERTSON DAY 1 / LORNA ROBERTSON DAY 2",
        "JUNCTION",
        False,
        "2-day race; both days from JUNCTION",
    ),
    ("bott", "Bott Cup", "BOTT", "TOP", False, ""),
    ("inter-club", "Inter-Club Challenge", "INTER-CLUB CHALLENGE", "JUNCTION", False, ""),
    ("seniors-stream", "Seniors From Stream", "SENIORS STREAM", "JUNCTION", False, ""),
    ("bonsai", "Bonsai Challenge", "BONSAI", "JUNCTION", False, ""),
    ("prince-philip", "Prince Philip Trophy", "PRINCE PHILIP", "TOP", False, ""),
    ("bucherer", "Bucherer Trophy", "BUCHERER", "TOP", False, ""),
    (
        "lowe-portago",
        "Lowe Portago Challenge Cup",
        "LOWE PORTAGO",
        "TOP",
        False,
        "Position uncertain; appears in web log but few PDF results",
    ),
    ("cresta-family", "Cresta Family Cup", "FAMILY", "TOP", False, ""),
    (
        "army-junction",
        "Army Junction Championship",
        "ARMY (J)",
        "JUNCTION",
        False,
        "Unofficial army championship from Junction",
    ),
    (
        "army-top",
        "Army Top Championship",
        "ARMY (T)",
        "TOP",
        False,
        "Unofficial army championship from Top",
    ),
    ("children", "Children's Race", "CHILDREN'S", "TOP", False, "Members' children's event"),
    ("junior-children", "Junior Children's Race", "JUNIOR CHILDREN'S", "TOP", False, ""),
    (
        "combination",
        "Combination Race",
        "COMBINATION",
        "BOTH",
        False,
        "Combined TOP/JUNCTION format",
    ),
    ("adjunct", "Adjunct", "ADJUNCT", "BOTH", False, "Adjunct event; position varies"),
    ("international", "International", "INTERNATIONAL", "TOP", False, ""),
    ("f-s-bros", "F&S and Bros", "F&S and BROS", "TOP", False, ""),
    ("seiler", "Seiler", "SEILER", "TOP", False, ""),
    ("junction-hcap", "Junction Handicap", "JUNCTION H'CAP", "JUNCTION", False, ""),
    ("monobob", "Monobob", "MONOBOB", "TOP", False, "Non-toboggan event"),
    ("night-riding", "Night Riding", "NIGHT RIDING", "BOTH", False, "Special evening session"),
]

# Mapping from raw DB names → canonical race_key
RAW_NAME_MAP = {
    # Practice
    "PRACTICE": "practice",
    # Nino Bibbia
    "NINO BIBBIA CHALLENGE CUP": "nino-bibbia",
    "THE NINO BIBBIA CHALLENGE CUP": "nino-bibbia",
    # University
    "THE UNIVERSITY CHALLENGE": "university",
    # Baron Oertzen
    "BARON OERTZEN CUP": "baron-oertzen",
    "THE BARON OERTZEN CUP": "baron-oertzen",
    # Bledisloe
    "BLEDISLOE CUP": "bledisloe",
    "THE BLEDISLOE CUP": "bledisloe",
    # Fairchilds MacCarthy (only in filenames/DB)
    # (parsed from PDF as part of a different race - not a standalone DB entry)
    # Heaton
    "HEATON GOLD CUP": "heaton",
    "THE HEATON GOLD CUP": "heaton",
    # Lightning
    "LIGHTNING CUP": "lightning",
    "THE LIGHTNING CUP": "lightning",
    # Curzon
    "CURZON CUP": "curzon",
    "THE CURZON CUP": "curzon",
    # Harjes Cartier
    "THE HARJES CARTIER SILVER CHIP": "harjes-cartier",
    # Escalante
    "ESCALANTE CUP": "escalante",
    "THE ESCALANTE CUP": "escalante",
    # Calisch Grischun
    "THE CALISCH GRISCHUN": "calisch-grischun",
    "CALISCH GRISCHUN": "calisch-grischun",
    # Aris Vatimbella
    "ARIS VATIMBELLA CHALLENGE CUP": "aris-vatimbella",
    "THE ARIS VATIMBELLA CHALLENGE CUP": "aris-vatimbella",
    # Swiss
    "SWISS CHAMPIONSHIP": "swiss",
    "THE SWISS CHAMPIONSHIP": "swiss",
    # Knapp
    "KNAPP CUP": "knapp",
    "THE KNAPP CUP": "knapp",
    # Stagni
    "STAGNI CUP": "stagni",
    "THE STAGNI CUP": "stagni",
    # Harland
    "HARLAND TROPHY": "harland",
    "THE HARLAND TROPHY": "harland",
    # Inter Services
    "THE INTER SERVICES CHAMPIONSHIP": "inter-services",
    # Silver Spoon
    "SERVICES' SILVER SPOON": "silver-spoon",
    "THE SERVICES' SILVER SPOON": "silver-spoon",
    "THE SERVICES WOMEN'S RACE": "ladies-services",
    # Morgan
    "MORGAN CUP": "morgan",
    "THE MORGAN CUP": "morgan",
    "HELD WITHIN THE MORGAN CUP": "morgan",  # annotation, not a real race
    # Hans Badrutt
    "HANS BADRUTT CHALLENGE CUP": "hans-badrutt",
    "Incorporating the HANS BADRUTT CHALLENGE CUP": "hans-badrutt",  # annotation
    # Brabazon
    "BRABAZON TROPHY": "brabazon",
    "THE BRABAZON TROPHY": "brabazon",
    "Followed by THE BRABAZON TROPHY": "brabazon",  # annotation
    # Roger Gibbs
    "ROGER GIBBS CHALLENGE CUP": "roger-gibbs",
    "THE ROGER GIBBS CHALLENGE CUP": "roger-gibbs",
    # Julian Board
    "JULIAN BOARD SENIORS CUP": "julian-board",
    "THE JULIAN BOARD SENIORS CUP": "julian-board",
    "Followed by THE JULIAN BOARD SENIORS CUP": "julian-board",  # annotation
    # Crawford
    "CRAWFORD CUP": "crawford",
    "THE CRAWFORD CUP": "crawford",
    "Alternating with THE CRAWFORD CUP": "crawford",  # annotation
    # Coppa d'Italia
    "COPPA d'ITALIA": "coppa-ditalia",
    "THE COPPA d'ITALIA": "coppa-ditalia",
    # Coppetta
    "THE COPPETTA D'ITALIA": "coppetta",
    "THE COPPETTA d'ITALIA": "coppetta",
    # Grand National
    "THE GRAND NATIONAL": "grand-national",
    # Johannes Badrutt
    "JOHANNES BADRUTT MEMORIAL TROPHY": "johannes-badrutt",
    "THE JOHANNES BADRUTT MEMORIAL TROPHY": "johannes-badrutt",
    # Glattfelder
    "GLATTFELDER CUP": "glattfelder",
    "THE GLATTFELDER CUP": "glattfelder",
    "Followed by THE GLATTFELDER CUP": "glattfelder",  # annotation
    # Marsden
    "MARSDEN CUP": "marsden",
    "THE MARSDEN CUP": "marsden",
    "Alternating each course with THE MARSDEN CUP": "marsden",  # annotation
    # President's Race
    "PRESIDENT'S RACE": "presidents",
    "THE PRESIDENT'S RACE": "presidents",
    "Followed by THE PRESIDENT's RACE": "presidents",  # annotation
    # Gunter Sachs
    "GUNTER SACHS CHALLENGE CUP": "gunter-sachs",
    "THE GUNTER SACHS CHALLENGE CUP": "gunter-sachs",
    # Claude Cartier
    "CLAUDE CARTIER CHALLENGE CUP": "claude-cartier",
    "THE CLAUDE CARTIER CHALLENGE CUP": "claude-cartier",
    # End of Term
    "END OF TERM RACE": "end-of-term",
    # Willoughby
    "WILLOUGHBY CUP": "willoughby",
    "THE WILLOUGHBY CUP": "willoughby",
    # Ladies
    "LADIES' RACE": "ladies",
    "THE LADIES EVENT": "ladies",
    # Nigel Moores
    "NIGEL MOORES MEMORIAL RACE": "nigel-moores",
    "THE NIGEL MOORES MEMORIAL RACE": "nigel-moores",
    # Payne Cup
    "PAYNE CUP": "payne-cup",
    "THE PAYNE CUP": "payne-cup",
    "Followed by THE PAYNE CUP": "payne-cup",  # annotation
    # Lorna Robertson (typo and correct versions)
    "LORNA ROBERSTSON CUP": "lorna-robertson",  # typo in PDF
    "THE LORNA ROBERSTSON CUP": "lorna-robertson",  # typo in PDF
    "LORNA ROBERTSON CHALLENGE CUP": "lorna-robertson",
    "THE LORNA ROBERTSON CHALLENGE CUP": "lorna-robertson",
    "Followed by THE LORNA ROBERTSON CHALLENGE CUP": "lorna-robertson",  # annotation
    # Bott
    "BOTT CUP": "bott",
    "THE BOTT CUP": "bott",
    # Inter Club
    "INTER CLUB EVENT": "inter-club",
    # Seniors Stream
    "SENIORS FROM STREAM": "seniors-stream",
    # Bonsai
    "BONSAI CHALLENGE": "bonsai",
    "Followed by THE BONSAI CHALLENGE": "bonsai",  # annotation
    # Prince Philip
    "PRINCE PHILIP TROPHY": "prince-philip",
    # Bucherer
    "BUCHERER TROPHY": "bucherer",
    # Lowe Portago
    "LOWE PORTAGO CHALLENGE CUP": "lowe-portago",
    # Cresta Family
    "CRESTA FAMILY CUP": "cresta-family",
    "Followed by Cresta Family Cup": "cresta-family",  # annotation
    # Army
    "Army Unofficial Junction Championship": "army-junction",
    # Children's
    "Children's Race": "children",
    "Members' Children's Race": "children",
    # Misc / one-offs that appear in DB (possibly noise or rarely-run)
    "BUCHERER TROPHY": "bucherer",
    "Ralph Hubbard Prize": "adjunct",  # one-off prize within another race
    "Ronnie Ramsay Rae Memorial Trophy": "adjunct",  # one-off
    "Speed Cup": "adjunct",
    # Unicode curly-apostrophe variants (same races, different encoding in source PDFs)
    "COPPA d’ITALIA": "coppa-ditalia",
    "Children’s Race": "children",
    "LADIES’ RACE": "ladies",
    "Members’ Children’s Race": "children",
    "SERVICES’ SILVER SPOON": "silver-spoon",
}

# Annotations to flag (these are not standalone races, just PDF header notes)
ANNOTATION_PATTERNS = [
    "Followed by",
    "Alternating",
    "Incorporating",
    "HELD WITHIN",
    "Alternating each course",
]


def load_db_races(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT race_id, name, date, start_position, is_practice FROM races ORDER BY date")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def load_web_scrape(data_dir: Path) -> list[dict]:
    path = data_dir / "web_scrape_log.json"
    with open(path) as f:
        return json.load(f)


def is_annotation(name: str) -> bool:
    return any(name.startswith(p) for p in ANNOTATION_PATTERNS)


def build_master_table(
    canonical_races: list, raw_name_map: dict, db_races: list, web_events: list
) -> list[dict]:
    # Build lookup: race_key → canonical info
    canonical_lookup = {r[0]: r for r in canonical_races}

    # Collect all raw DB names and their actual positions
    db_positions = defaultdict(set)
    for race in db_races:
        db_positions[race["name"]].add(race["start_position"])

    # Collect web event coverage by short title
    web_seasons = defaultdict(set)
    for ev in web_events:
        title = ev.get("event_title", "")
        season = ev.get("season", "")
        # Strip trailing year
        parts = title.rsplit(" ", 1)
        if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 4:
            short = parts[0]
        else:
            short = title
        if short and "PRACTICE" not in short and short != "Practice":
            web_seasons[short].add(season)

    rows = []
    for key, canonical_name, web_short, position, is_practice, notes in canonical_races:
        # Find all raw DB name variants that map to this key
        db_variants = [raw for raw, k in raw_name_map.items() if k == key]

        # Check actual DB positions for this key's variants
        actual_positions = set()
        for variant in db_variants:
            actual_positions.update(db_positions.get(variant, set()))

        # Seasons from web scrape
        seasons = web_seasons.get(web_short, set())
        # Handle multi-day web titles
        if "/" in web_short:
            for part in web_short.split(" / "):
                seasons.update(web_seasons.get(part.strip(), set()))

        rows.append(
            {
                "race_key": key,
                "canonical_name": canonical_name,
                "web_title_short": web_short,
                "start_position": position,
                "is_practice": int(is_practice),
                "db_name_variants": "; ".join(sorted(set(db_variants))),
                "db_positions_observed": "; ".join(sorted(actual_positions))
                if actual_positions
                else "",
                "seasons_in_web": "; ".join(sorted(seasons)) if seasons else "",
                "notes": notes,
            }
        )

    return rows


def main():
    # Resolve data dir
    data_dir = Path(__file__).parent.parent.parent.parent.parent.parent / "smtc-handicap" / "data"
    # Simple relative: go up from worktree
    project_root = Path(__file__).parent.parent
    # The worktree is at .worktrees/calendar; data is at ../../data relative to worktree
    data_dir = project_root.parent.parent / "data"
    db_path = data_dir / "cresta.db"

    print(f"Loading DB from {db_path}")
    db_races = load_db_races(db_path)
    print(f"Loaded {len(db_races)} races from DB")

    web_events = load_web_scrape(data_dir)
    print(f"Loaded {len(web_events)} events from web scrape log")

    rows = build_master_table(CANONICAL_RACES, RAW_NAME_MAP, db_races, web_events)

    out_path = data_dir / "race_master.csv"
    fieldnames = [
        "race_key",
        "canonical_name",
        "web_title_short",
        "start_position",
        "is_practice",
        "db_name_variants",
        "db_positions_observed",
        "seasons_in_web",
        "notes",
    ]

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Written {len(rows)} races to {out_path}")

    # Also print summary
    print("\n=== RACE MASTER TABLE ===")
    print(f"{'KEY':<25} {'CANONICAL NAME':<45} {'POSITION':<10} {'PRACTICE'}")
    print("-" * 90)
    for r in rows:
        print(
            f"{r['race_key']:<25} {r['canonical_name']:<45} {r['start_position']:<10} {bool(r['is_practice'])}"
        )

    # Cross-reference: DB names not yet mapped
    all_raw_db_names = {race["name"] for race in db_races}
    unmapped = all_raw_db_names - set(RAW_NAME_MAP.keys())
    non_annotation_unmapped = [n for n in sorted(unmapped) if not is_annotation(n)]
    if non_annotation_unmapped:
        print(f"\n=== UNMAPPED DB NAMES ({len(non_annotation_unmapped)}) ===")
        for n in non_annotation_unmapped:
            print(f"  '{n}'")


if __name__ == "__main__":
    main()
