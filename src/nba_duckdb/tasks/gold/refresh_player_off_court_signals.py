"""Refresh legal/free off-court player popularity snapshots.

Sources are intentionally limited to no-key public APIs plus optional local
user-supplied ranking snapshots. The repository does not ship ranking data.
"""

from __future__ import annotations

import json
import logging
import os
import time
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from nba_duckdb.db import read_table, upsert_rows

logger = logging.getLogger("nba_duckdb.tasks.gold.player_off_court_signals")

DEFAULT_OFF_COURT_REFRESH_LIMIT = 25
DEFAULT_OFF_COURT_REQUEST_DELAY_SECONDS = 0.5
USER_AGENT = "nba-analytics-pipeline/0.1 (local analytics pipeline)"
WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"
WIKIMEDIA_PAGEVIEWS_ENDPOINT = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia.org/all-access/user"
GDELT_DOC_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"


def _normalize_name(value: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_name.lower().replace(".", "").split())


def _wikipedia_title_from_name(value: str) -> str:
    return "_".join(value.strip().split())


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _load_jersey_rank_snapshot() -> dict[str, Any] | None:
    path_raw = os.environ.get("NBA_DUCKDB_JERSEY_RANKS_FILE", "").strip()
    if not path_raw:
        return None

    path = Path(path_raw).expanduser()
    payload = json.loads(path.read_text())
    required_fields = [
        "snapshot_date",
        "season",
        "list_name",
        "release_title",
        "source_name",
        "source_url",
        "ranks",
    ]
    missing = [field for field in required_fields if field not in payload]
    if missing:
        raise ValueError(
            f"Jersey rank file {path} is missing required fields: {', '.join(missing)}"
        )
    if not isinstance(payload["ranks"], list):
        raise ValueError(f"Jersey rank file {path} must contain a list-valued 'ranks' field")

    ranks_by_name: dict[str, int] = {}
    for entry in payload["ranks"]:
        if not isinstance(entry, dict):
            raise ValueError(f"Jersey rank file {path} contains a non-object rank entry")
        player_name = str(entry.get("player_name") or "").strip()
        if not player_name:
            raise ValueError(f"Jersey rank file {path} contains a rank entry without player_name")
        ranks_by_name[_normalize_name(player_name)] = int(entry["rank"])

    if not ranks_by_name:
        raise ValueError(f"Jersey rank file {path} did not contain any rank entries")

    return {
        "snapshot_date": str(payload["snapshot_date"]),
        "season": str(payload["season"]),
        "list_name": str(payload["list_name"]),
        "release_title": str(payload["release_title"]),
        "source_name": str(payload["source_name"]),
        "source_url": str(payload["source_url"]),
        "ranks_by_name": ranks_by_name,
    }


def _resolve_wikidata_identity(client: httpx.Client, player_name: str) -> dict[str, Any] | None:
    escaped_name = player_name.replace('"', '\\"')
    query = f"""
    SELECT ?item ?article WHERE {{
      ?item rdfs:label ?label .
      FILTER(LANG(?label) = "en")
      FILTER(LCASE(STR(?label)) = LCASE("{escaped_name}"))
      ?item wdt:P106/wdt:P279* wd:Q3665646 .
      OPTIONAL {{
        ?article schema:about ?item ;
                 schema:isPartOf <https://en.wikipedia.org/> .
      }}
    }}
    LIMIT 2
    """
    try:
        response = client.get(
            WIKIDATA_ENDPOINT,
            params={"query": query, "format": "json"},
            headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
            timeout=20,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.info("Wikidata lookup skipped for %s: %s", player_name, exc)
        return None

    bindings = response.json().get("results", {}).get("bindings", [])
    if len(bindings) != 1:
        return None
    item = bindings[0].get("item", {}).get("value", "")
    article = bindings[0].get("article", {}).get("value", "")
    qid = item.rsplit("/", 1)[-1] if item else ""
    title = article.rsplit("/wiki/", 1)[-1] if "/wiki/" in article else ""
    return {
        "wikidata_qid": qid,
        "wikipedia_title": title or _wikipedia_title_from_name(player_name),
        "source_confidence": 0.9 if title else 0.65,
        "source_note": "Wikidata exact-label basketball-player match",
    }


def _fetch_pageviews(
    client: httpx.Client, player_id: int, title: str, days: int = 30
) -> list[dict[str, Any]]:
    end = _today_utc() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    page_path = f"{quote(title, safe='')}/daily/{start:%Y%m%d}00/{end:%Y%m%d}00"
    url = f"{WIKIMEDIA_PAGEVIEWS_ENDPOINT}/{page_path}"
    try:
        response = client.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            logger.info("Pageviews skipped for %s: %s", title, exc)
        return []
    except httpx.HTTPError as exc:
        logger.info("Pageviews skipped for %s: %s", title, exc)
        return []
    rows = []
    for item in response.json().get("items", []):
        stamp = str(item.get("timestamp") or "")
        if len(stamp) < 8:
            continue
        rows.append(
            {
                "player_id": player_id,
                "view_date": f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}",
                "wikipedia_title": title.replace("_", " "),
                "views": int(item.get("views") or 0),
                "source_name": "Wikipedia",
                "source_url": f"https://en.wikipedia.org/wiki/{title}",
            }
        )
    return rows


def _fetch_gdelt_mentions(client: httpx.Client, player: dict[str, Any]) -> list[dict[str, Any]]:
    player_name = str(player.get("full_name") or player.get("player_name") or "")
    if not player_name:
        return []
    query = f'"{player_name}" (NBA OR basketball)'
    try:
        response = client.get(
            GDELT_DOC_ENDPOINT,
            params={
                "query": query,
                "mode": "artlist",
                "maxrecords": 75,
                "timespan": "7d",
                "sort": "datedesc",
                "format": "json",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=25,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.info("GDELT skipped for %s: %s", player_name, exc)
        return []

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for article in response.json().get("articles", []):
        raw_date = str(article.get("seendate") or article.get("date") or "")
        day = raw_date[:8]
        if len(day) == 8:
            grouped[f"{day[0:4]}-{day[4:6]}-{day[6:8]}"].append(article)

    rows = []
    for mention_date, articles in grouped.items():
        rows.append(
            {
                "player_id": int(player["player_id"]),
                "mention_date": mention_date,
                "article_count": len(articles),
                "headline_count": len(articles),
                "tone_avg": None,
                "query": query,
                "sample_headlines": json.dumps(
                    [
                        {
                            "title": article.get("title"),
                            "url": article.get("url"),
                            "domain": article.get("domain"),
                        }
                        for article in articles[:5]
                    ]
                ),
                "source_name": "GDELT",
                "source_url": "https://www.gdeltproject.org/",
            }
        )
    return rows


def refresh(
    limit: int | None = None,
    request_delay_seconds: float = DEFAULT_OFF_COURT_REQUEST_DELAY_SECONDS,
) -> dict[str, int]:
    players = read_table("silver", "dim_players", "is_active = TRUE").to_dicts()
    if limit is not None:
        players = players[:limit]
    identity_rows = {
        int(row["player_id"]): row
        for row in read_table("silver", "dim_player_external_identities").to_dicts()
        if row.get("player_id") is not None
    }

    identity_writes: list[dict[str, Any]] = []
    pageview_writes: list[dict[str, Any]] = []
    media_writes: list[dict[str, Any]] = []
    jersey_writes: list[dict[str, Any]] = []
    jersey_snapshot = _load_jersey_rank_snapshot()

    if os.environ.get("NBA_DUCKDB_OFFLINE_SMOKE") == "1":
        for rank, player in enumerate(players, start=1):
            player_id = int(player["player_id"])
            player_name = str(player.get("full_name") or player.get("player_name") or "")
            title = (
                identity_rows.get(player_id, {}).get("wikipedia_title")
                or _wikipedia_title_from_name(player_name)
            )
            pageview_writes.append(
                {
                    "player_id": player_id,
                    "view_date": "2100-01-01",
                    "wikipedia_title": str(title).replace("_", " "),
                    "views": 1000 + rank,
                    "source_name": "Synthetic smoke fixture",
                    "source_url": "synthetic-fixture",
                }
            )
            media_writes.append(
                {
                    "player_id": player_id,
                    "mention_date": "2100-01-01",
                    "article_count": 1 + rank % 3,
                    "headline_count": 1 + rank % 3,
                    "tone_avg": None,
                    "query": f'"{player_name}" synthetic',
                    "sample_headlines": json.dumps([]),
                    "source_name": "Synthetic smoke fixture",
                    "source_url": "synthetic-fixture",
                }
            )
            jersey_writes.append(
                {
                    "player_id": player_id,
                    "snapshot_date": "2100-01-01",
                    "season": str(player.get("season") or "2099-00"),
                    "rank": rank,
                    "list_name": "Synthetic Smoke Rankings",
                    "release_title": "Synthetic fixture ranking",
                    "source_name": "Synthetic smoke fixture",
                    "source_url": "synthetic-fixture",
                }
            )
        return {
            "identities": 0,
            "pageviews": upsert_rows(
                "gold", "player_pageviews_daily", pageview_writes, ["player_id", "view_date"]
            )
            if pageview_writes
            else 0,
            "media_mentions": upsert_rows(
                "gold", "player_media_mentions_daily", media_writes, ["player_id", "mention_date"]
            )
            if media_writes
            else 0,
            "jersey_ranks": upsert_rows(
                "gold",
                "player_jersey_rank_snapshots",
                jersey_writes,
                ["player_id", "snapshot_date", "list_name"],
            )
            if jersey_writes
            else 0,
        }

    with httpx.Client(follow_redirects=True) as client:
        for index, player in enumerate(players):
            player_id = int(player["player_id"])
            player_name = str(player.get("full_name") or player.get("player_name") or "")
            identity = identity_rows.get(player_id)
            if not identity:
                resolved = _resolve_wikidata_identity(client, player_name) or {
                    "wikidata_qid": "",
                    "wikipedia_title": _wikipedia_title_from_name(player_name),
                    "source_confidence": 0.4,
                    "source_note": (
                        "Name-based Wikipedia title fallback; verify before using social mappings"
                    ),
                }
                identity = {"player_id": player_id, **resolved}
                identity_writes.append(identity)

            title = str(identity.get("wikipedia_title") or "").replace(" ", "_")
            if title:
                pageview_writes.extend(_fetch_pageviews(client, player_id, title))
            media_writes.extend(_fetch_gdelt_mentions(client, player))

            jersey_rank = (
                jersey_snapshot["ranks_by_name"].get(_normalize_name(player_name))
                if jersey_snapshot
                else None
            )
            if jersey_rank is not None and jersey_snapshot:
                jersey_writes.append(
                    {
                        "player_id": player_id,
                        "snapshot_date": jersey_snapshot["snapshot_date"],
                        "season": jersey_snapshot["season"],
                        "rank": jersey_rank,
                        "list_name": jersey_snapshot["list_name"],
                        "release_title": jersey_snapshot["release_title"],
                        "source_name": jersey_snapshot["source_name"],
                        "source_url": jersey_snapshot["source_url"],
                    }
                )

            if request_delay_seconds > 0 and index < len(players) - 1:
                time.sleep(request_delay_seconds)

    counts = {
        "identities": upsert_rows(
            "silver", "dim_player_external_identities", identity_writes, ["player_id"]
        )
        if identity_writes
        else 0,
        "pageviews": upsert_rows(
            "gold", "player_pageviews_daily", pageview_writes, ["player_id", "view_date"]
        )
        if pageview_writes
        else 0,
        "media_mentions": upsert_rows(
            "gold", "player_media_mentions_daily", media_writes, ["player_id", "mention_date"]
        )
        if media_writes
        else 0,
        "jersey_ranks": upsert_rows(
            "gold",
            "player_jersey_rank_snapshots",
            jersey_writes,
            ["player_id", "snapshot_date", "list_name"],
        )
        if jersey_writes
        else 0,
    }
    logger.info("Refreshed off-court signals: %s", counts)
    return counts


def run(**_kwargs) -> dict[str, int]:
    limit_raw = os.environ.get(
        "OFF_COURT_REFRESH_LIMIT",
        str(DEFAULT_OFF_COURT_REFRESH_LIMIT),
    ).strip()
    limit = None if limit_raw.lower() in {"", "all", "none"} else int(limit_raw)
    delay_raw = os.environ.get(
        "OFF_COURT_REQUEST_DELAY_SECONDS",
        str(DEFAULT_OFF_COURT_REQUEST_DELAY_SECONDS),
    ).strip()
    request_delay_seconds = float(delay_raw or 0)
    return refresh(limit=limit, request_delay_seconds=request_delay_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    run()

# Pipeline graph declaration. Kept with task code so contributors can find ownership.
TASK_DEF = {'layer': 'gold',
 'task_type': 'gold',
 'inputs': ('silver.dim_players', 'silver.dim_player_external_identities'),
 'optional_inputs': (),
 'outputs': ('gold.player_pageviews_daily',
             'gold.player_media_mentions_daily',
             'gold.player_jersey_rank_snapshots'),
 'mutates': (),
 'graphs': ('default',),
 'modes': ('live', 'fixture'),
 'required': True,
 'quality_outputs': ('gold.player_pageviews_daily',
                     'gold.player_media_mentions_daily',
                     'gold.player_jersey_rank_snapshots'),
 'regular_season_only': True,
 'live_order': 570,
 'fixture_order': 450}
