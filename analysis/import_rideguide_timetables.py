#!/usr/bin/env python3
"""Download current date-specific CityLink timetables from Ride Guide.

This importer uses the same timetable endpoint used by the Ride Guide web
application:

    https://api.app.ride.guide/v2/timetable?routeId=1102&date=YYYYMMDD

The response contains current route metadata, directions, stop names and
coordinates, paired stops, trip IDs, and complete stop times.

Authentication is supplied through the RIDEGUIDE_API_KEY environment variable.
The key is intentionally never stored in this repository.

Outputs:
  raw/<date>/<route_id>.json
  routes.csv
  stops.csv
  trips.csv
  stop_times.csv
  service_dates.csv
  import_summary.json

The importer is intentionally low-frequency. It sleeps between requests and
only queries the route/date combinations requested by the caller.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_URL = "https://api.app.ride.guide/v2/timetable"
APP_ORIGIN = "https://app.ride.guide"
APP_REFERER = "https://app.ride.guide/"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/153.0.0.0 Safari/537.36"
)

ROUTES: Dict[str, Tuple[str, str]] = {
    "1102": ("2", "Onerahi"),
    "1103": ("3", "Tikipunga (via Kamo)"),
    "1109": ("3A", "Kamo (via Tikipunga)"),
    "1104": ("4", "Otangarei"),
    "1105": ("5", "Morningside (via NorthTec)"),
    "1110": ("5A", "Raumanga (via Morningside)"),
    "1106": ("6", "Maunu"),
    "1107": ("7", "Fairway Drive"),
    "1108": ("8", "Southern Express"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import current date-specific CityLink timetables from Ride Guide."
    )
    parser.add_argument(
        "--date",
        action="append",
        dest="dates",
        help="Service date as YYYY-MM-DD or YYYYMMDD. May be repeated.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="If --date is omitted, fetch this many consecutive days starting today (default: 7).",
    )
    parser.add_argument(
        "--route-id",
        action="append",
        dest="route_ids",
        help="Ride Guide route ID. May be repeated. Defaults to all known CityLink routes.",
    )
    parser.add_argument("--output-dir", default="data/rideguide_timetables")
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.35,
        help="Pause between requests (default: 0.35 seconds).",
    )
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    return parser.parse_args()


def parse_service_date(value: str) -> date:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Invalid service date: {value!r}")


def requested_dates(args: argparse.Namespace) -> List[date]:
    if args.dates:
        return sorted({parse_service_date(value) for value in args.dates})
    if args.days <= 0:
        raise ValueError("--days must be greater than zero")
    start = date.today()
    return [start + timedelta(days=offset) for offset in range(args.days)]


def requested_routes(args: argparse.Namespace) -> List[str]:
    route_ids = args.route_ids or list(ROUTES)
    unknown = sorted(set(route_ids) - set(ROUTES))
    if unknown:
        raise ValueError(f"Unknown CityLink route ID(s): {', '.join(unknown)}")
    return sorted(set(route_ids), key=lambda value: int(value))


def get_api_key() -> str:
    api_key = os.environ.get("RIDEGUIDE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "RIDEGUIDE_API_KEY is not set. Configure it as a secret/environment variable before running the importer."
        )
    return api_key


def fetch_timetable(
    route_id: str,
    service_date: date,
    timeout: float,
    api_key: str,
) -> Dict[str, Any]:
    query = urlencode({"routeId": route_id, "date": service_date.strftime("%Y%m%d")})
    url = f"{API_URL}?{query}"
    request = Request(
        url,
        headers={
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "Origin": APP_ORIGIN,
            "Referer": APP_REFERER,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "User-Agent": BROWSER_USER_AGENT,
            "x-api-key": api_key,
        },
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(
            f"Unexpected response type for route {route_id} on {service_date}: {type(payload)}"
        )
    return payload


def write_csv(path: Path, rows: Iterable[Dict[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def normalize(
    payloads: List[Tuple[date, str, Dict[str, Any]]]
) -> Tuple[List[Dict[str, Any]], ...]:
    route_rows: Dict[Tuple[str, str], Dict[str, Any]] = {}
    stop_rows: Dict[str, Dict[str, Any]] = {}
    trip_rows: Dict[Tuple[str, str, int, str], Dict[str, Any]] = {}
    stop_time_rows: List[Dict[str, Any]] = []
    service_rows: List[Dict[str, Any]] = []

    for service_date, requested_route_id, payload in payloads:
        route_id = str(payload.get("routeId") or requested_route_id)
        route_short = str(payload.get("routeShortName") or ROUTES.get(route_id, ("", ""))[0])
        route_long = str(payload.get("routeLongName") or ROUTES.get(route_id, ("", ""))[1])
        payload_date = str(payload.get("date") or service_date.strftime("%Y%m%d"))

        route_rows[(route_id, payload_date)] = {
            "service_date": service_date.isoformat(),
            "agency_id": payload.get("agencyId", ""),
            "route_id": route_id,
            "route_short_name": route_short,
            "route_long_name": route_long,
            "route_color": payload.get("routeColor", ""),
            "route_text_color": payload.get("routeTextColor", ""),
        }

        total_trips = 0
        direction_names: List[str] = []
        for direction in payload.get("directions") or []:
            if not isinstance(direction, dict):
                continue
            direction_id = direction.get("id", "")
            direction_name = str(direction.get("directionName") or "")
            if direction_name:
                direction_names.append(direction_name)

            for stop in direction.get("stops") or []:
                if not isinstance(stop, dict):
                    continue
                stop_id = str(stop.get("id") or "").strip()
                if not stop_id:
                    continue
                location = stop.get("location") or []
                longitude = location[0] if len(location) >= 1 else ""
                latitude = location[1] if len(location) >= 2 else ""
                existing = stop_rows.get(stop_id)
                candidate = {
                    "stop_id": stop_id,
                    "stop_code": stop.get("stopCode", ""),
                    "stop_name": stop.get("name", ""),
                    "latitude": latitude,
                    "longitude": longitude,
                    "paired_stop_id": stop.get("pairedStopId", ""),
                    "is_primary": stop.get("isPrimary", ""),
                    "timepoint_seen": stop.get("timepoint", ""),
                }
                if existing is None or (
                    not existing.get("stop_name") and candidate.get("stop_name")
                ):
                    stop_rows[stop_id] = candidate

            trips = direction.get("trips") or []
            total_trips += len(trips)
            for trip in trips:
                if not isinstance(trip, dict):
                    continue
                trip_id = str(trip.get("tripId") or "").strip()
                if not trip_id:
                    continue
                stop_times = [
                    row for row in (trip.get("stopTimes") or []) if isinstance(row, dict)
                ]
                first = stop_times[0] if stop_times else {}
                last = stop_times[-1] if stop_times else {}
                trip_rows[(payload_date, route_id, int(direction_id), trip_id)] = {
                    "service_date": service_date.isoformat(),
                    "route_id": route_id,
                    "route_short_name": route_short,
                    "route_long_name": route_long,
                    "direction_id": direction_id,
                    "direction_name": direction_name,
                    "trip_id": trip_id,
                    "first_stop_id": first.get("id", ""),
                    "first_time": first.get("time", ""),
                    "last_stop_id": last.get("id", ""),
                    "last_time": last.get("time", ""),
                    "stop_count": len(stop_times),
                }

                for stop_time in stop_times:
                    stop_time_rows.append(
                        {
                            "service_date": service_date.isoformat(),
                            "route_id": route_id,
                            "route_short_name": route_short,
                            "direction_id": direction_id,
                            "direction_name": direction_name,
                            "trip_id": trip_id,
                            "stop_id": stop_time.get("id", ""),
                            "stop_sequence": stop_time.get("sequence", ""),
                            "scheduled_time": stop_time.get("time", ""),
                            "timepoint": stop_time.get("timepoint", ""),
                            "pickup_type": stop_time.get("pickupType", ""),
                            "drop_off_type": stop_time.get("dropOffType", ""),
                        }
                    )

        service_rows.append(
            {
                "service_date": service_date.isoformat(),
                "weekday": service_date.strftime("%A"),
                "route_id": route_id,
                "route_short_name": route_short,
                "route_long_name": route_long,
                "trip_count": total_trips,
                "direction_count": len(payload.get("directions") or []),
                "direction_names": ";".join(sorted(set(direction_names))),
            }
        )

    return (
        sorted(
            route_rows.values(),
            key=lambda row: (row["service_date"], int(row["route_id"])),
        ),
        sorted(stop_rows.values(), key=lambda row: row["stop_id"]),
        sorted(
            trip_rows.values(),
            key=lambda row: (
                row["service_date"],
                int(row["route_id"]),
                int(row["direction_id"]),
                row["first_time"],
                row["trip_id"],
            ),
        ),
        sorted(
            stop_time_rows,
            key=lambda row: (
                row["service_date"],
                int(row["route_id"]),
                int(row["direction_id"]),
                row["trip_id"],
                int(row["stop_sequence"]),
            ),
        ),
        sorted(
            service_rows,
            key=lambda row: (row["service_date"], int(row["route_id"])),
        ),
    )


def main() -> None:
    args = parse_args()
    api_key = get_api_key()
    dates = requested_dates(args)
    route_ids = requested_routes(args)
    output_dir = Path(args.output_dir)
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    payloads: List[Tuple[date, str, Dict[str, Any]]] = []
    errors: List[Dict[str, str]] = []

    for service_date in dates:
        for route_id in route_ids:
            try:
                payload = fetch_timetable(
                    route_id,
                    service_date,
                    args.timeout_seconds,
                    api_key,
                )
            except Exception as exc:  # Keep other route/date imports usable.
                errors.append(
                    {
                        "service_date": service_date.isoformat(),
                        "route_id": route_id,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                print(f"ERROR {route_id} {service_date}: {type(exc).__name__}: {exc}")
            else:
                date_dir = raw_dir / service_date.strftime("%Y%m%d")
                date_dir.mkdir(parents=True, exist_ok=True)
                raw_path = date_dir / f"{route_id}.json"
                raw_path.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                payloads.append((service_date, route_id, payload))
                print(f"OK {route_id} {service_date} -> {raw_path}")
            if args.delay_seconds > 0:
                time.sleep(args.delay_seconds)

    routes, stops, trips, stop_times, service_dates = normalize(payloads)

    write_csv(
        output_dir / "routes.csv",
        routes,
        [
            "service_date",
            "agency_id",
            "route_id",
            "route_short_name",
            "route_long_name",
            "route_color",
            "route_text_color",
        ],
    )
    write_csv(
        output_dir / "stops.csv",
        stops,
        [
            "stop_id",
            "stop_code",
            "stop_name",
            "latitude",
            "longitude",
            "paired_stop_id",
            "is_primary",
            "timepoint_seen",
        ],
    )
    write_csv(
        output_dir / "trips.csv",
        trips,
        [
            "service_date",
            "route_id",
            "route_short_name",
            "route_long_name",
            "direction_id",
            "direction_name",
            "trip_id",
            "first_stop_id",
            "first_time",
            "last_stop_id",
            "last_time",
            "stop_count",
        ],
    )
    write_csv(
        output_dir / "stop_times.csv",
        stop_times,
        [
            "service_date",
            "route_id",
            "route_short_name",
            "direction_id",
            "direction_name",
            "trip_id",
            "stop_id",
            "stop_sequence",
            "scheduled_time",
            "timepoint",
            "pickup_type",
            "drop_off_type",
        ],
    )
    write_csv(
        output_dir / "service_dates.csv",
        service_dates,
        [
            "service_date",
            "weekday",
            "route_id",
            "route_short_name",
            "route_long_name",
            "trip_count",
            "direction_count",
            "direction_names",
        ],
    )

    summary = {
        "source": API_URL,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dates_requested": [value.isoformat() for value in dates],
        "route_ids_requested": route_ids,
        "requests_expected": len(dates) * len(route_ids),
        "responses_ok": len(payloads),
        "responses_failed": len(errors),
        "routes_rows": len(routes),
        "stops": len(stops),
        "trips": len(trips),
        "stop_times": len(stop_times),
        "errors": errors,
        "note": (
            "Current date-specific passenger timetable data from Ride Guide; "
            "not an archived PDF and not inferred from realtime observations."
        ),
    }
    (output_dir / "import_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(summary, indent=2))
    if not payloads:
        raise SystemExit("No timetable responses were imported successfully.")


if __name__ == "__main__":
    main()
