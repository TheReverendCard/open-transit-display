#!/usr/bin/env python3
"""Compare NRC ArcGIS route attributes with Ride Guide realtime route IDs.

The script scans all NRC CSV attributes for exact or normalized matches to
route_id values observed in collected Ride Guide data.  This helps determine
whether NRC's open GIS layer exposes the same identifiers, or whether mapping
must be based on names/geometry instead.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare NRC ArcGIS fields against Ride Guide route IDs.")
    parser.add_argument("--nrc-csv", required=True)
    parser.add_argument("--realtime", required=True, help="Collector file or directory")
    parser.add_argument("--output-dir", default="data/source_compare")
    return parser.parse_args()


def iter_files(source: Path) -> Iterable[Path]:
    if source.is_file():
        yield source
        return
    for pattern in ("*.jsonl.gz", "*.jsonl"):
        yield from source.rglob(pattern)


def iter_json_rows(path: Path) -> Iterable[Dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).strip().lower())


def main() -> None:
    args = parse_args()
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    realtime_ids: Set[str] = set()
    for path in iter_files(Path(args.realtime)):
        for row in iter_json_rows(path):
            route_id = str(row.get("route_id") or "").strip()
            if route_id:
                realtime_ids.add(route_id)

    with Path(args.nrc_csv).open("r", encoding="utf-8-sig", newline="") as handle:
        nrc_rows = list(csv.DictReader(handle))

    comparisons: List[Dict[str, Any]] = []
    normalized_ids = {norm(route_id): route_id for route_id in realtime_ids}

    for index, row in enumerate(nrc_rows, start=1):
        for field, value in row.items():
            if value is None or str(value).strip() == "":
                continue
            raw = str(value).strip()
            matched = ""
            match_type = ""
            if raw in realtime_ids:
                matched = raw
                match_type = "exact"
            elif norm(raw) in normalized_ids:
                matched = normalized_ids[norm(raw)]
                match_type = "normalized_exact"
            else:
                for route_id in sorted(realtime_ids):
                    if route_id and route_id in raw:
                        matched = route_id
                        match_type = "contains"
                        break
            if matched:
                comparisons.append({
                    "nrc_row": index,
                    "nrc_field": field,
                    "nrc_value": raw,
                    "rideguide_route_id": matched,
                    "match_type": match_type,
                })

    fields = ["nrc_row", "nrc_field", "nrc_value", "rideguide_route_id", "match_type"]
    with (outdir / "route_id_matches.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(comparisons)

    summary = {
        "rideguide_route_ids": sorted(realtime_ids),
        "nrc_feature_rows": len(nrc_rows),
        "matches_found": len(comparisons),
        "matched_route_ids": sorted({row["rideguide_route_id"] for row in comparisons}),
        "unmatched_route_ids": sorted(realtime_ids - {row["rideguide_route_id"] for row in comparisons}),
        "note": "No match does not mean no relationship; names and geometry may still provide a mapping.",
    }
    (outdir / "route_id_comparison_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
