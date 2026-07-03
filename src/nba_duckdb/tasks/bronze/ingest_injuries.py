"""Bronze: Ingest current NBA injury report from the NBA's official published PDFs.

The NBA publishes official injury reports at ak-static.cms.nba.com before each
game day. These are public documents required by league rules and intended for
media/public consumption. URL pattern:
    Injury-Report_YYYY-MM-DD_HH_MMAM.pdf  (e.g. Injury-Report_2026-01-01_07_00PM.pdf)

Strategy: probe candidate times (latest-first) for today and yesterday until we
find a PDF that exists, then parse it with pdfplumber and store the extracted
rows as JSON.
"""

import io
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone

import httpx

from nba_duckdb.db import upsert_rows

logger = logging.getLogger("nba_duckdb.tasks.bronze.injuries")

BASE_URL = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_{date}_{time}.pdf"

# Candidate times in reverse chronological order (latest report of the day first).
# NBA games tip off at various ET times; injury report updates are published ~2h prior.
_CANDIDATE_TIMES = [
    "11_30PM", "11_00PM", "10_30PM", "10_00PM", "09_30PM", "09_00PM",
    "08_30PM", "08_00PM", "07_30PM", "07_00PM", "06_30PM", "06_00PM",
    "05_30PM", "05_00PM", "04_45PM", "04_30PM", "04_00PM", "03_30PM",
    "03_00PM", "02_30PM", "02_00PM", "01_30PM", "01_00PM", "12_30PM",
    "12_00PM", "11_30AM", "11_00AM",
]


def _find_latest_pdf(client: httpx.Client) -> tuple[str, bytes] | tuple[None, None]:
    """Try candidate dates/times and return (url, bytes) for the first PDF found."""
    today = date.today()
    for delta in (0, 1, 2):  # today, yesterday, day before
        check_date = (today - timedelta(days=delta)).strftime("%Y-%m-%d")
        for time_slot in _CANDIDATE_TIMES:
            url = BASE_URL.format(date=check_date, time=time_slot)
            try:
                resp = client.head(url, timeout=10)
                if resp.status_code == 200:
                    logger.info("Found injury report: %s", url)
                    resp = client.get(url, timeout=60)
                    resp.raise_for_status()
                    return url, resp.content
            except httpx.HTTPError:
                continue
    return None, None


def _col(x0: float) -> str | None:
    """Map an x-coordinate to a column name based on the NBA injury report layout."""
    if x0 < 100:
        return "game_date"
    if x0 < 195:
        return "game_time"
    if x0 < 258:
        return "matchup"
    if x0 < 415:
        return "team"
    if x0 < 578:
        return "player"
    if x0 < 658:
        return "status"
    return "reason"


# Column headers and structural text to skip
_SKIP_TEXTS = frozenset({
    "GameDate", "GameTime", "Matchup", "Team", "PlayerName", "CurrentStatus", "Reason",
})

# Full NBA team names (no spaces, lowercase) → 3-letter abbreviation
_TEAM_NAME_MAP = {
    "atlantahawks": "ATL",       "bostonceltics": "BOS",
    "brooklynnets": "BKN",       "charlottehornets": "CHA",
    "chicagobulls": "CHI",       "clevelandcavaliers": "CLE",
    "dallasmavericks": "DAL",    "denvernuggets": "DEN",
    "detroitpistons": "DET",     "goldenstatewarriors": "GSW",
    "houstonrockets": "HOU",     "indianapacers": "IND",
    "losangelesclippers": "LAC", "losangeleslakers": "LAL",
    "memphisgrizzlies": "MEM",   "miamiheat": "MIA",
    "milwaukeebucks": "MIL",
    "minnesotatimberwolves": "MIN",
    "neworleanspelicans": "NOP", "newyorkknicks": "NYK",
    "oklahomacitythunder": "OKC","orlandomagic": "ORL",
    "philadelphia76ers": "PHI",  "phoenixsuns": "PHX",
    "portlandtrailblazers": "POR","sacramentokings": "SAC",
    "sanantoniospurs": "SAS",    "torontoraptors": "TOR",
    "utahjazz": "UTA",           "washingtonwizards": "WAS",
}


def _parse_pdf(pdf_bytes: bytes) -> list[dict]:
    """Extract injury rows from the NBA injury report PDF.

    The NBA injury PDF has no cell borders — words are positioned spatially.
    Strategy:
    1. Extract words with (x0, global_top) where global_top = page_offset + page_top,
       ensuring y-coordinates are unique across all pages.
    2. Skip page header/footer words (page-relative top < 110 or text is structural).
    3. Identify "player rows" — lines with text in the player column (x0 ≈ 415-578).
    4. Reason text spans multiple y-rows around the player line; assign reason words
       using the midpoint between consecutive players as the partition boundary.
    5. Game context (team, matchup, date, time) propagates forward through running state.
    """
    import bisect
    try:
        import pdfplumber
    except ModuleNotFoundError:
        logger.warning("pdfplumber is not installed; skipping injury report parsing")
        return []

    all_words = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page_offset = 0.0
        for page in pdf.pages:
            page_h = float(page.height)
            for w in page.extract_words(x_tolerance=3, y_tolerance=3):
                page_top = float(w["top"])
                # Skip page header (title + column labels) and footer (page numbers)
                if page_top < 110 or page_top > page_h - 80:
                    continue
                if w["text"] in _SKIP_TEXTS:
                    continue
                if w["text"].startswith("Page") and "of" in w["text"]:
                    continue
                all_words.append({
                    "x0": float(w["x0"]),
                    "top": page_offset + page_top,
                    "text": w["text"],
                })
            page_offset += page_h

    if not all_words:
        return []

    all_words.sort(key=lambda w: (w["top"], w["x0"]))

    # Player rows: words in player column (x0 ≈ 415-578), deduplicated by rounded top
    player_tops = sorted({
        round(w["top"], 1)
        for w in all_words if 415 <= w["x0"] < 578
    })

    if not player_tops:
        return []

    # Partition boundaries for assigning reason text to the right player
    boundaries = [0.0]
    for i in range(1, len(player_tops)):
        boundaries.append((player_tops[i - 1] + player_tops[i]) / 2.0)
    boundaries.append(float("inf"))

    player_reason: dict[float, list[str]] = {pt: [] for pt in player_tops}
    player_status: dict[float, str] = {}
    player_name_map: dict[float, str] = {}

    # Context that carries forward (game_date, game_time, matchup, team)
    running: dict[str, str] = {}
    game_ctx: dict[float, dict] = {}  # player_top -> snapshotted context

    player_top_set = set(player_tops)

    for w in all_words:
        col = _col(w["x0"])
        top = w["top"]
        rounded = round(top, 1)
        text = w["text"]

        if col == "reason":
            idx = bisect.bisect_right(boundaries, top) - 1
            idx = max(0, min(idx, len(player_tops) - 1))
            player_reason[player_tops[idx]].append(text)

        elif col == "status":
            nearest = min(player_tops, key=lambda pt: abs(pt - top))
            if nearest not in player_status:
                player_status[nearest] = text

        elif col in ("game_date", "game_time", "matchup", "team"):
            running[col] = text

        elif col == "player":
            if rounded in player_top_set:
                game_ctx[rounded] = dict(running)
                player_name_map[rounded] = text

    rows = []
    for pt in player_tops:
        player_name = player_name_map.get(pt, "").strip()
        status = player_status.get(pt, "").strip()
        if not player_name or not status:
            continue

        ctx = game_ctx.get(pt, {})
        raw_team = ctx.get("team", "")
        team_abbr = _TEAM_NAME_MAP.get(raw_team.lower().replace(" ", ""), raw_team)
        reason = " ".join(player_reason.get(pt, [])).strip()

        rows.append({
            "game_date": ctx.get("game_date", ""),
            "game_time": ctx.get("game_time", ""),
            "matchup": ctx.get("matchup", ""),
            "team_abbr": team_abbr,
            "player_name": player_name,
            "status": status,
            "reason": reason,
        })
    return rows


def run(**kwargs):
    if os.environ.get("NBA_DUCKDB_OFFLINE_SMOKE") == "1":
        raise RuntimeError("Live injury-report HTTP calls are disabled during offline smoke runs")

    with httpx.Client(follow_redirects=True) as client:
        url, pdf_bytes = _find_latest_pdf(client)

    if not pdf_bytes:
        logger.warning("No NBA injury report PDF found for today or yesterday — skipping")
        return {"rows_written": 0}

    rows_parsed = _parse_pdf(pdf_bytes)
    logger.info("Parsed %d injury entries from %s", len(rows_parsed), url)

    today = date.today().isoformat()
    bronze_rows = [{
        "fetched_date": today,
        "injuries_json": json.dumps({
            "source_url": url,
            "fetched_date": today,
            "rows": rows_parsed,
        }),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }]
    count = upsert_rows("bronze", "injuries", bronze_rows, conflict_cols=["fetched_date"])
    logger.info("Upserted injury snapshot (%d players) for %s", len(rows_parsed), today)
    return {"rows_written": count}

# Pipeline graph declaration. Kept with task code so contributors can find ownership.
TASK_DEF = {'layer': 'bronze',
 'task_type': 'bronze',
 'inputs': (),
 'optional_inputs': (),
 'outputs': ('bronze.injuries',),
 'mutates': (),
 'graphs': ('default',),
 'modes': ('live',),
 'required': True,
 'quality_outputs': ('bronze.injuries',),
 'regular_season_only': True,
 'live_order': 130,
 'fixture_order': None}
