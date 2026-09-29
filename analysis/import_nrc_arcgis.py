#!/usr/bin/env python3
"""Download NRC bus route open data from ArcGIS and save normalized outputs.

This importer is intended to complement static GTFS reconstruction. It fetches
NRC's public Bus Routes (Open Data) FeatureServer layer, preserves all source
attributes, writes GeoJSON, and writes a flattened CSV for easy comparison with
Ride Guide realtime route IDs.

The default layer corresponds to the NRC ArcGIS item discussed in the project:
https://data-nrcgis.opendata.arcgis.com/maps/6a53905e2cb14929abe358f45cd209b9

Usage:
    python analysis/import_nrc_arcgis.py

Optional:
    python analysis/import_nrc_arcgis.py \
        --layer-url "https://.../FeatureServer/0" \
        --output-dir data/nrc_arcgis
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

import requests


DEFAULT_LAYER_URL = (
    "https://services2.arcgis.com/J8errK5dyxu7Xjf7/arcgis/rest/services/"
    "Bus_Routes_%28Open_Data%29/FeatureServer/0"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download and normalize NRC ArcGIS bus route open data."
    )
    parser.add_argument(
        "--layer-url",
        default=DEFAULT_LAYER_URL,
        help="ArcGIS FeatureServer layer URL ending in /FeatureServer/<layer>.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/nrc_arcgis",
        help="Directory for GeoJSON, CSV, and metadata outputs.",
    )
    return parser.parse_args()


def get_json(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    response = requests.get(url, params=params, timeout=60)
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(f"ArcGIS error: {payload['error']}")
    return payload


def fetch_metadata(layer_url: str) -> Dict[str, Any]:
    return get_json(layer_url, {"f": "json"})


def fetch_object_ids(layer_url: str) -> List[int]:
    payload = get_json(
        f"{layer_url}/query",
        {
            "f": "json",
            "where": "1=1",
            "returnIdsOnly": "true",
        },
    )
    return [int(value) for value in payload.get("objectIds", [])]


def chunked(values: List[int], size: int) -> Iterable[List[int]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def fetch_features(layer_url: str, object_ids: List[int]) -> List[Dict[str, Any]]:
    if not object_ids:
        return []

    features: List[Dict[str, Any]] = []
    for chunk in chunked(object_ids, 500):
        payload = get_json(
            f"{layer_url}/query",
            {
                "f": "geojson",
                "objectIds": ",".join(str(value) for value in chunk),
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": "4326",
            },
        )
        features.extend(payload.get("features", []))
    return features


def flatten_geometry(geometry: Dict[str, Any] | None) -> Dict[str, Any]:
    if not geometry:
        return {
            "geometry_type": "",
            "geometry_json": "",
            "bbox_min_lon": "",
            "bbox_min_lat": "",
            "bbox_max_lon": "",
            "bbox_max_lat": "",
        }

    coordinates = geometry.get("coordinates")
    lons: List[float] = []
    lats: List[float] = []

    def walk(value: Any) -> None:
        if (
            isinstance(value, list)
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            lons.append(float(value[0]))
            lats.append(float(value[1]))
            return
        if isinstance(value, list):
            for item in value:
                walk(item)

    walk(coordinates)

    return {
        "geometry_type": geometry.get("type", ""),
        "geometry_json": json.dumps(geometry, separators=(",", ":")),
        "bbox_min_lon": min(lons) if lons else "",
        "bbox_min_lat": min(lats) if lats else "",
        "bbox_max_lon": max(lons) if lons else "",
        "bbox_max_lat": max(lats) if lats else "",
    }


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: List[str] = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    layer_url = args.layer_url.rstrip("/")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Fetching ArcGIS layer metadata: {layer_url}")
    metadata = fetch_metadata(layer_url)

    object_ids = fetch_object_ids(layer_url)
    print(f"Found {len(object_ids)} features")

    features = fetch_features(layer_url, object_ids)

    geojson = {
        "type": "FeatureCollection",
        "features": features,
    }

    geojson_path = output_dir / "nrc_bus_routes.geojson"
    geojson_path.write_text(
        json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    metadata_path = output_dir / "nrc_bus_routes_metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    rows: List[Dict[str, Any]] = []
    for feature in features:
        row = dict(feature.get("properties") or {})
        row.update(flatten_geometry(feature.get("geometry")))
        rows.append(row)

    csv_path = output_dir / "nrc_bus_routes.csv"
    write_csv(csv_path, rows)

    fields = metadata.get("fields", [])
    print("ArcGIS source fields:")
    for field in fields:
        print(f"  {field.get('name')}: {field.get('alias', '')}")

    print(f"Wrote {geojson_path}")
    print(f"Wrote {csv_path}")
    print(f"Wrote {metadata_path}")

    if rows:
        print("Sample feature attributes:")
        for key, value in rows[0].items():
            if key == "geometry_json":
                continue
            print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
