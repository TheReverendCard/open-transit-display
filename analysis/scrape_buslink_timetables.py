#!/usr/bin/env python3
"""Scrape published CityLink timetables from BusLink into normalized CSV files.

The goal is not to create official GTFS.  It preserves the human-facing
published timetable so it can be matched against Ride Guide's machine IDs.

Outputs:
  published_routes.csv
  published_timetable.csv
  scrape_summary.json

Example:
  python analysis/scrape_buslink_timetables.py \
      --output-dir data/published_timetables
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag


CITYLINK_URL = "https://www.buslink.co.nz/bus-services/citylink"
USER_AGENT = "open-transit-display/0.1 (+https://github.com/TheReverendCard/open-transit-display)"
TIME_RE = re.compile(
    r"^\s*(\d{1,2})[\.:](\d{2})(?:\s*([ap])\.?m\.?)?\s*$",
    re.IGNORECASE,
)
ROUTE_RE = re.compile(r"^\s*(\d+[a-zA-Z]?)\s+(.+?)(?:\s+View timetable)?\s*$", re.IGNORECASE)


FALLBACK_ROUTES = [
    ("2", "Onerahi", "/bus-services/citylink/onerahi/"),
    ("3", "Tikipunga (via Kamo)", "/bus-services/citylink/tikipunga-via-te-kamo/"),
    ("3a", "Kamo (via Tikipunga)", "/bus-services/citylink/te-kamo-via-tikipunga/"),
    ("4", "Otangarei", "/bus-services/citylink/otangarei/"),
    ("5", "Morningside (via Northtec)", "/bus-services/citylink/morningside-via-northtec/"),
    ("5a", "Raumanga (via Morningside)", "/bus-services/citylink/raumanga-via-morningside/"),
    ("6", "Maunu", "/bus-services/citylink/maunu/"),
    ("7", "Fairway Drive", "/bus-services/citylink/fairway-drive/"),
    ("8", "Southern Express", "/bus-services/citylink/southern-express/"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape BusLink CityLink published timetables.")
    parser.add_argument("--output-dir", default="data/published_timetables")
    parser.add_argument("--citylink-url", default=CITYLINK_URL)
    parser.add_argument("--timeout", type=int, default=60)
    return parser.parse_args()


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def fetch_html(s: requests.Session, url: str, timeout: int) -> str:
    response = s.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def clean_text(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def parse_route_label(text: str) -> Optional[Tuple[str, str]]:
    text = clean_text(text)
    match = ROUTE_RE.match(text)
    if not match:
        return None
    route = match.group(1).lower()
    name = clean_text(match.group(2))
    if name.lower().endswith("view timetable"):
        name = clean_text(name[: -len("view timetable")])
    return route, name


def discover_routes(html: str, base_url: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    found: Dict[str, Dict[str, str]] = {}

    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        if "/bus-services/citylink/" not in href:
            continue
        if href.rstrip("/") == "/bus-services/citylink":
            continue

        parsed = parse_route_label(anchor.get_text(" ", strip=True))
        if not parsed:
            # Some cards put route text outside the anchor.  Try the parent.
            parent_text = anchor.parent.get_text(" ", strip=True) if anchor.parent else ""
            parsed = parse_route_label(parent_text)
        if not parsed:
            continue

        route_public, route_name = parsed
        found[route_public] = {
            "route_public": route_public,
            "route_name": route_name,
            "url": urljoin(base_url, href),
            "source": "discovered_from_citylink_page",
        }

    for route_public, route_name, href in FALLBACK_ROUTES:
        found.setdefault(
            route_public,
            {
                "route_public": route_public,
                "route_name": route_name,
                "url": urljoin(base_url, href),
                "source": "fallback_route_list",
            },
        )

    def sort_key(row: Dict[str, str]) -> Tuple[int, str]:
        match = re.match(r"(\d+)(.*)", row["route_public"])
        return (int(match.group(1)) if match else 9999, match.group(2) if match else row["route_public"])

    return sorted(found.values(), key=sort_key)


def preceding_headings(table: Tag, limit: int = 5) -> List[str]:
    headings: List[str] = []
    for node in table.find_all_previous(["h1", "h2", "h3", "h4", "h5", "h6"], limit=limit):
        text = clean_text(node.get_text(" ", strip=True))
        if text:
            headings.append(text)
    headings.reverse()
    return headings


def context_period(context: str) -> str:
    text = context.lower()
    if re.search(r"\bmorning\b|\bam\b|a\.m\.", text):
        return "AM"
    if re.search(r"\bafternoon\b|\bevening\b|\bpm\b|p\.m\.", text):
        return "PM"
    return ""


def service_days_from_context(context: str) -> str:
    text = context.lower()
    if "monday to friday" in text or "monday - friday" in text or "weekdays" in text:
        return "Monday;Tuesday;Wednesday;Thursday;Friday"
    if "saturday" in text and "sunday" in text:
        return "Saturday;Sunday"
    if "saturday" in text:
        return "Saturday"
    if "sunday" in text:
        return "Sunday"

    days = []
    for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
        if day.lower() in text:
            days.append(day)
    return ";".join(days)


def parse_clock(value: str, period_hint: str) -> Tuple[Optional[int], str]:
    text = clean_text(value)
    match = TIME_RE.match(text)
    if not match:
        return None, ""

    hour = int(match.group(1))
    minute = int(match.group(2))
    suffix = (match.group(3) or "").lower()
    if hour > 24 or minute > 59:
        return None, ""

    confidence = "ambiguous_12h"
    if suffix:
        if hour == 12:
            hour = 0
        if suffix == "p":
            hour += 12
        confidence = "explicit_ampm"
    elif period_hint == "AM":
        if hour == 12:
            hour = 0
        confidence = "section_am"
    elif period_hint == "PM":
        if 1 <= hour <= 11:
            hour += 12
        confidence = "section_pm"
    elif hour >= 13:
        confidence = "explicit_24h"

    return hour * 60 + minute, confidence


def table_matrix(table: Tag) -> List[List[str]]:
    matrix: List[List[str]] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        row = [clean_text(cell.get_text(" ", strip=True)) for cell in cells]
        if any(row):
            matrix.append(row)
    return matrix


def parse_table(
    table: Tag,
    route: Dict[str, str],
    table_index: int,
) -> List[Dict[str, Any]]:
    matrix = table_matrix(table)
    if not matrix:
        return []

    headings = preceding_headings(table)
    context = " | ".join(headings)
    period_hint = context_period(context)
    service_days = service_days_from_context(context)

    rows: List[Dict[str, Any]] = []

    # Detect simple vertical Stop | Time tables.
    if max(len(row) for row in matrix) <= 3:
        vertical_pairs = []
        for row_index, row in enumerate(matrix):
            if len(row) < 2:
                continue
            minutes, confidence = parse_clock(row[-1], period_hint)
            if minutes is None:
                continue
            stop_label = clean_text(" ".join(row[:-1]))
            vertical_pairs.append((row_index, stop_label, row[-1], minutes, confidence))

        if len(vertical_pairs) >= 2:
            for seq, (row_index, stop_label, time_text, minutes, confidence) in enumerate(vertical_pairs, start=1):
                rows.append(
                    {
                        "source": "buslink_published_timetable",
                        "official_gtfs": "false",
                        "route_public": route["route_public"],
                        "route_name": route["route_name"],
                        "route_url": route["url"],
                        "table_index": table_index,
                        "trip_index": 0,
                        "timing_point_sequence": seq,
                        "timing_point_label": stop_label,
                        "published_time": time_text,
                        "published_minutes": minutes,
                        "time_parse_confidence": confidence,
                        "period_hint": period_hint,
                        "service_days": service_days,
                        "section_context": context,
                        "parser_mode": "vertical",
                        "source_row_index": row_index,
                    }
                )
            return rows

    # Wide timetable.  Pick the first row that looks more like labels than times.
    header_index = 0
    best_header_score = -1
    for idx, row in enumerate(matrix[:4]):
        time_count = sum(parse_clock(cell, period_hint)[0] is not None for cell in row)
        label_score = len(row) - time_count
        if label_score > best_header_score and len(row) >= 2:
            best_header_score = label_score
            header_index = idx
    headers = matrix[header_index]

    trip_index = 0
    for source_row_index, row in enumerate(matrix[header_index + 1 :], start=header_index + 1):
        parsed_cells = [parse_clock(cell, period_hint) for cell in row]
        if sum(minutes is not None for minutes, _ in parsed_cells) < 2:
            continue

        trip_index += 1
        max_cols = min(len(row), len(headers))
        seq = 0
        for col in range(max_cols):
            minutes, confidence = parsed_cells[col]
            if minutes is None:
                continue
            seq += 1
            label = headers[col] if col < len(headers) else f"Column {col + 1}"
            rows.append(
                {
                    "source": "buslink_published_timetable",
                    "official_gtfs": "false",
                    "route_public": route["route_public"],
                    "route_name": route["route_name"],
                    "route_url": route["url"],
                    "table_index": table_index,
                    "trip_index": trip_index,
                    "timing_point_sequence": seq,
                    "timing_point_label": label,
                    "published_time": row[col],
                    "published_minutes": minutes,
                    "time_parse_confidence": confidence,
                    "period_hint": period_hint,
                    "service_days": service_days,
                    "section_context": context,
                    "parser_mode": "wide",
                    "source_row_index": source_row_index,
                }
            )

    return rows


def write_csv(path: Path, rows: Iterable[Dict[str, Any]], fields: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    s = session()
    citylink_html = fetch_html(s, args.citylink_url, args.timeout)
    routes = discover_routes(citylink_html, args.citylink_url)

    timetable_rows: List[Dict[str, Any]] = []
    route_rows: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []

    for route in routes:
        try:
            html = fetch_html(s, route["url"], args.timeout)
            soup = BeautifulSoup(html, "html.parser")
            tables = soup.find_all("table")
            parsed_count = 0
            for table_index, table in enumerate(tables, start=1):
                parsed = parse_table(table, route, table_index)
                timetable_rows.extend(parsed)
                parsed_count += len(parsed)

            route_rows.append(
                {
                    **route,
                    "http_ok": "true",
                    "tables_found": len(tables),
                    "normalized_rows": parsed_count,
                }
            )
        except Exception as exc:
            failures.append({"route_public": route["route_public"], "url": route["url"], "error": str(exc)})
            route_rows.append(
                {
                    **route,
                    "http_ok": "false",
                    "tables_found": 0,
                    "normalized_rows": 0,
                }
            )

    route_fields = ["route_public", "route_name", "url", "source", "http_ok", "tables_found", "normalized_rows"]
    timetable_fields = [
        "source",
        "official_gtfs",
        "route_public",
        "route_name",
        "route_url",
        "table_index",
        "trip_index",
        "timing_point_sequence",
        "timing_point_label",
        "published_time",
        "published_minutes",
        "time_parse_confidence",
        "period_hint",
        "service_days",
        "section_context",
        "parser_mode",
        "source_row_index",
    ]

    write_csv(output_dir / "published_routes.csv", route_rows, route_fields)
    write_csv(output_dir / "published_timetable.csv", timetable_rows, timetable_fields)

    summary = {
        "source": args.citylink_url,
        "routes_discovered_or_fallback": len(routes),
        "routes_fetched": sum(1 for row in route_rows if row["http_ok"] == "true"),
        "routes_failed": len(failures),
        "normalized_timetable_rows": len(timetable_rows),
        "failures": failures,
        "note": "Published passenger timetable normalized for matching. This is not an official GTFS feed.",
    }
    (output_dir / "scrape_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print(f"Wrote {output_dir / 'published_routes.csv'}")
    print(f"Wrote {output_dir / 'published_timetable.csv'}")
    print(f"Wrote {output_dir / 'scrape_summary.json'}")


if __name__ == "__main__":
    main()
