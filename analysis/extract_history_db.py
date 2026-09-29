#!/usr/bin/env python3
"""Extract a provisional route/trip/stop catalogue from a Ride Guide history SQLite DB.

This script is intended for locally captured databases such as ``bus_history.db``.
It does not claim to produce official GTFS.  It derives a compact, inspectable
catalogue from captured Ride Guide vehicle positions, trip updates, and stop
predictions.

Outputs:
  routes_trips.csv
  trip_stop_patterns.csv
  stops.csv
  extract_summary.json

The schedule backbone uses only ``SCHEDULE_BASED`` stop predictions.  For each
route/trip/stop-sequence combination, the most frequently observed departure
(or arrival, when departure is absent) timestamp is retained as the canonical
captured time.  Stability columns show whether that timestamp remained fixed
throughout the capture.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


ROUTE_MAP = {
    "1102": ("2", "Onerahi"),
    "1103": ("3", "Tikipunga (via Kamo)"),
    "1109": ("3a", "Kamo (via Tikipunga)"),
    "1104": ("4", "Otangarei"),
    "1105": ("5", "Morningside (via Northtec)"),
    "1110": ("5a", "Raumanga (via Morningside)"),
    "1106": ("6", "Maunu"),
    "1107": ("7", "Fairway Drive"),
    "1108": ("8", "Southern Express"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract a provisional transit catalogue from a Ride Guide SQLite history database."
    )
    parser.add_argument("--db", required=True, help="Path to bus_history.db-style SQLite database")
    parser.add_argument("--output-dir", default="data/history_extract")
    parser.add_argument("--timezone", default="Pacific/Auckland")
    return parser.parse_args()


def public_route(route_id: object) -> str:
    return ROUTE_MAP.get(str(route_id), ("", ""))[0]


def route_name(route_id: object) -> str:
    return ROUTE_MAP.get(str(route_id), ("", ""))[1]


def format_local_time(series: pd.Series, timezone: str) -> pd.Series:
    return (
        pd.to_datetime(series, unit="s", utc=True, errors="coerce")
        .dt.tz_convert(timezone)
        .dt.strftime("%Y-%m-%d %H:%M:%S%z")
    )


def build_trip_stop_patterns(conn: sqlite3.Connection, timezone: str) -> pd.DataFrame:
    sp = pd.read_sql_query(
        """
        SELECT route_id, trip_id, stop_sequence, stop_id,
               departure_time, arrival_time, received_at
        FROM stop_predictions
        WHERE prediction_source='SCHEDULE_BASED'
        """,
        conn,
    )

    group_cols = ["route_id", "trip_id", "stop_sequence", "stop_id"]
    sp["canonical_time"] = sp["departure_time"].fillna(sp["arrival_time"])

    agg = (
        sp.groupby(group_cols, dropna=False)
        .agg(
            observations=("stop_id", "size"),
            first_seen=("received_at", "min"),
            last_seen=("received_at", "max"),
            distinct_departure_times=("departure_time", lambda s: s.dropna().nunique()),
            distinct_arrival_times=("arrival_time", lambda s: s.dropna().nunique()),
            min_departure_time=("departure_time", "min"),
            max_departure_time=("departure_time", "max"),
            min_arrival_time=("arrival_time", "min"),
            max_arrival_time=("arrival_time", "max"),
        )
        .reset_index()
    )

    mode = (
        sp.dropna(subset=["canonical_time"])
        .groupby(group_cols + ["canonical_time"])
        .size()
        .reset_index(name="canonical_time_observations")
        .sort_values(
            group_cols + ["canonical_time_observations", "canonical_time"],
            ascending=[True, True, True, True, False, True],
        )
        .drop_duplicates(group_cols)
        .rename(columns={"canonical_time": "canonical_time_unix"})
    )

    patterns = agg.merge(mode, on=group_cols, how="left")
    patterns["time_source"] = np.where(
        patterns["min_departure_time"].notna(), "departure", "arrival"
    )
    patterns["time_span_seconds"] = np.where(
        patterns["min_departure_time"].notna(),
        patterns["max_departure_time"] - patterns["min_departure_time"],
        patterns["max_arrival_time"] - patterns["min_arrival_time"],
    )
    patterns["stable_exact"] = (
        (patterns["distinct_departure_times"] <= 1)
        & (patterns["distinct_arrival_times"] <= 1)
    )
    patterns["canonical_time_nz"] = format_local_time(
        patterns["canonical_time_unix"], timezone
    )
    patterns["public_route"] = patterns["route_id"].map(public_route)
    patterns["route_name"] = patterns["route_id"].map(route_name)

    fields = [
        "public_route",
        "route_name",
        "route_id",
        "trip_id",
        "stop_sequence",
        "stop_id",
        "canonical_time_nz",
        "canonical_time_unix",
        "time_source",
        "observations",
        "canonical_time_observations",
        "distinct_departure_times",
        "distinct_arrival_times",
        "time_span_seconds",
        "stable_exact",
        "first_seen",
        "last_seen",
    ]
    return patterns[fields].sort_values(
        ["route_id", "trip_id", "stop_sequence", "stop_id"]
    )


def build_routes_trips(
    conn: sqlite3.Connection, patterns: pd.DataFrame, timezone: str
) -> pd.DataFrame:
    trips = pd.read_sql_query(
        """
        SELECT
          route_id, trip_id,
          COUNT(DISTINCT stop_id) AS distinct_stop_ids,
          COUNT(DISTINCT stop_sequence) AS distinct_stop_sequences,
          MIN(stop_sequence) AS first_stop_sequence,
          MAX(stop_sequence) AS last_stop_sequence,
          MIN(received_at) AS first_seen,
          MAX(received_at) AS last_seen,
          SUM(prediction_source='SCHEDULE_BASED') AS schedule_based_rows,
          SUM(prediction_source='GPS_REALTIME') AS gps_realtime_rows,
          SUM(prediction_source='ASSIGNED_OR_HISTORICAL') AS assigned_or_historical_rows,
          SUM(prediction_source='UNKNOWN') AS unknown_rows
        FROM stop_predictions
        WHERE route_id IS NOT NULL AND route_id <> ''
          AND trip_id IS NOT NULL AND trip_id <> ''
        GROUP BY route_id, trip_id
        """,
        conn,
    )

    schedule_trips = (
        patterns.groupby(["route_id", "trip_id"])
        .agg(
            schedule_stop_rows=("stop_id", "size"),
            schedule_distinct_stops=("stop_id", "nunique"),
            schedule_first_time_unix=("canonical_time_unix", "min"),
            schedule_last_time_unix=("canonical_time_unix", "max"),
            schedule_exact_stable_rows=("stable_exact", "sum"),
        )
        .reset_index()
    )

    trips = trips.merge(schedule_trips, on=["route_id", "trip_id"], how="left")
    trips["public_route"] = trips["route_id"].map(public_route)
    trips["route_name"] = trips["route_id"].map(route_name)
    trips["schedule_first_time_nz"] = format_local_time(
        trips["schedule_first_time_unix"], timezone
    )
    trips["schedule_last_time_nz"] = format_local_time(
        trips["schedule_last_time_unix"], timezone
    )

    fields = [
        "public_route",
        "route_name",
        "route_id",
        "trip_id",
        "distinct_stop_ids",
        "distinct_stop_sequences",
        "first_stop_sequence",
        "last_stop_sequence",
        "schedule_stop_rows",
        "schedule_distinct_stops",
        "schedule_first_time_nz",
        "schedule_last_time_nz",
        "schedule_exact_stable_rows",
        "schedule_based_rows",
        "gps_realtime_rows",
        "assigned_or_historical_rows",
        "unknown_rows",
        "first_seen",
        "last_seen",
    ]
    return trips[fields].sort_values(["route_id", "trip_id"])


def build_stops(conn: sqlite3.Connection) -> pd.DataFrame:
    stop_routes = pd.read_sql_query(
        """
        SELECT stop_id, route_id, COUNT(*) AS observations,
               COUNT(DISTINCT trip_id) AS trip_count
        FROM stop_predictions
        WHERE stop_id IS NOT NULL AND stop_id <> ''
        GROUP BY stop_id, route_id
        """,
        conn,
    )

    stop_summary = (
        stop_routes.groupby("stop_id")
        .agg(
            route_ids=("route_id", lambda s: ";".join(sorted(set(str(x) for x in s if x)))),
            route_count=("route_id", lambda s: len(set(str(x) for x in s if x))),
            trip_count=("trip_count", "sum"),
            prediction_observations=("observations", "sum"),
        )
        .reset_index()
    )

    vp = pd.read_sql_query(
        """
        SELECT stop_id, current_status, latitude, longitude, received_at
        FROM vehicle_positions
        WHERE stop_id IS NOT NULL AND stop_id <> ''
        """,
        conn,
    )
    stopped = vp[vp["current_status"] == 1].copy()
    geo = (
        stopped.groupby("stop_id")
        .agg(
            stopped_at_observations=("stop_id", "size"),
            latitude_median=("latitude", "median"),
            longitude_median=("longitude", "median"),
            latitude_min=("latitude", "min"),
            latitude_max=("latitude", "max"),
            longitude_min=("longitude", "min"),
            longitude_max=("longitude", "max"),
            first_stopped_seen=("received_at", "min"),
            last_stopped_seen=("received_at", "max"),
        )
        .reset_index()
    )

    return stop_summary.merge(geo, on="stop_id", how="left").sort_values("stop_id")


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    with sqlite3.connect(db_path) as conn:
        patterns = build_trip_stop_patterns(conn, args.timezone)
        trips = build_routes_trips(conn, patterns, args.timezone)
        stops = build_stops(conn)

    patterns.to_csv(output_dir / "trip_stop_patterns.csv", index=False)
    trips.to_csv(output_dir / "routes_trips.csv", index=False)
    stops.to_csv(output_dir / "stops.csv", index=False)

    summary = {
        "database": db_path.name,
        "schedule_based_trip_stop_rows": int(len(patterns)),
        "schedule_based_trip_ids": int(patterns["trip_id"].nunique()),
        "schedule_based_route_ids": int(patterns["route_id"].nunique()),
        "distinct_stop_ids": int(stops["stop_id"].nunique()),
        "trip_route_pairs": int(len(trips)),
        "exactly_stable_schedule_rows": int(patterns["stable_exact"].sum()),
        "non_exact_schedule_rows": int((~patterns["stable_exact"]).sum()),
        "stops_with_stopped_at_coordinates": int(
            stops["stopped_at_observations"].notna().sum()
        ),
        "note": "Derived from captured Ride Guide data. These are not official GTFS files.",
    }
    (output_dir / "extract_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    print(json.dumps(summary, indent=2))
    print(f"Wrote {output_dir / 'routes_trips.csv'}")
    print(f"Wrote {output_dir / 'trip_stop_patterns.csv'}")
    print(f"Wrote {output_dir / 'stops.csv'}")
    print(f"Wrote {output_dir / 'extract_summary.json'}")


if __name__ == "__main__":
    main()
