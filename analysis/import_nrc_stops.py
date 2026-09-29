#!/usr/bin/env python3
"""Download Northland Regional Council's public CityLink bus-stop layer.

The NRC ArcGIS layer exposes passenger-facing stop names together with a numeric
``stop_id``.  Ride Guide uses stop identifiers in the same numeric namespace, so
this file is the preferred source for human-readable stop names.  The importer
preserves the NRC attributes and geometry and does not treat the result as GTFS.

Outputs:
  nrc_citylink_stops.csv
  nrc_citylink_stops.geojson
  nrc_citylink_stops_summary.json
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

import requests


DEFAULT_LAYER_URL = (
    "https://services2.arcgis.com/J8errK5dyxu7Xjf7/ArcGIS/rest/services/"
    "Bus_Routes_%28Open_Data%29/FeatureServer/0"
)
USER_AGENT = "open-transit-display/0.1 (+https://github.com/TheReverendCard/open-transit-display)"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download NRC CityLink bus stops.")
    parser.add_argument("--layer-url", default=DEFAULT_LAYER_URL)
    parser.add_argument("--output-dir", default="data/nrc_stops")
    parser.add_argument("--timeout", type=int, default=60)
    return parser.parse_args()


def get_json(url: str, params: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(json.dumps(payload["error"], ensure_ascii=False))
    return payload


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

    metadata = get_json(args.layer_url, {"f": "json"}, args.timeout)
    layer_name = metadata.get("name", "")
    geometry_type = metadata.get("geometryType", "")

    result = get_json(
        f"{args.layer_url}/query",
        {
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "geojson",
        },
        args.timeout,
    )

    features = result.get("features", [])
    rows: List[Dict[str, Any]] = []
    for feature in features:
        props = dict(feature.get("properties") or {})
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates") or []
        longitude = coords[0] if len(coords) >= 2 else None
        latitude = coords[1] if len(coords) >= 2 else None
        props["latitude"] = latitude
        props["longitude"] = longitude
        rows.append(props)

    field_names = [field.get("name") for field in metadata.get("fields", []) if field.get("name")]
    fields = field_names + [field for field in ["latitude", "longitude"] if field not in field_names]

    write_csv(output_dir / "nrc_citylink_stops.csv", rows, fields)
    (output_dir / "nrc_citylink_stops.geojson").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    stop_ids = [str(row.get("stop_id", "")).strip() for row in rows if str(row.get("stop_id", "")).strip()]
    stop_names = [str(row.get("stop_name", "")).strip() for row in rows if str(row.get("stop_name", "")).strip()]
    summary = {
        "layer_url": args.layer_url,
        "layer_name": layer_name,
        "geometry_type": geometry_type,
        "features": len(features),
        "distinct_stop_ids": len(set(stop_ids)),
        "distinct_stop_names": len(set(stop_names)),
        "has_stop_id_field": "stop_id" in field_names,
        "has_stop_name_field": "stop_name" in field_names,
        "note": "Northland Regional Council public GIS data; not GTFS.",
    }
    (output_dir / "nrc_citylink_stops_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Wrote {output_dir / 'nrc_citylink_stops.csv'}")
    print(f"Wrote {output_dir / 'nrc_citylink_stops.geojson'}")


if __name__ == "__main__":
    main()
