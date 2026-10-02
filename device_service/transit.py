"""GTFS-RT selector matching and snapshot change candidates.

Matching is AND within each selector and OR between selectors. Feed namespace
is mandatory. Match one actual departure context at a time, never cross-product
independent route/trip lists.
"""
import math


def applies(feed_id, alert, context):
    if context.get("feed_id") != feed_id:
        return False
    for selector in alert.get("informed_entity", []):
        if not selector or set(selector) - {"agency_id", "route_id", "route_type", "stop_id", "trip", "direction_id"}:
            continue
        matched = True
        for field, value in selector.items():
            if field == "trip":
                supported = {"trip_id", "route_id", "direction_id", "start_time", "start_date", "schedule_relationship"}
                matched &= bool(value) and not (set(value) - supported) and all(context.get(k) == v for k, v in value.items())
            else:
                matched &= context.get(field) == value
        if matched:
            return True
    return False


def active(alert, now):
    periods = alert.get("active_period", [])
    return not periods or any(p.get("start", 0) <= now < p.get("end", 2**63 - 1) for p in periods)


def distance_metres(a, b):
    lat1, lat2 = math.radians(float(a["stop_lat"])), math.radians(float(b["stop_lat"]))
    dlat = lat2 - lat1
    dlon = math.radians(float(b["stop_lon"]) - float(a["stop_lon"]))
    h = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(h)))


def stop_changes(previous, current, validated_complete=False, threshold_metres=50):
    """Only compare two successful complete snapshots. Removal is not proof of closure."""
    if not validated_complete:
        raise ValueError("complete validated snapshots required")
    result = []
    for stop_id, old in previous.items():
        new = current.get(stop_id)
        if new is None:
            result.append({"stop_id": stop_id, "type": "stop_missing", "review_required": True})
        elif distance_metres(old, new) >= threshold_metres:
            result.append({"stop_id": stop_id, "type": "stop_coordinates_changed", "review_required": True,
                           "distance_metres": round(distance_metres(old, new)), "old": old, "new": new})
    return result
