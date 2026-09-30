# Adapter for agencies without GTFS APIs

`collector/build_derived_gtfs.py` is the first adapter template, using CityLink's date-specific published timetable payloads.  It creates a standard GTFS ZIP with agency, routes, stops, trips, stop times, calendar exceptions and feed information.  Every service date gets distinct trip IDs and a mapping back to the provider's realtime IDs.  Original stop IDs are retained.  Times interpolated by the timetable provider have timepoint=0.  Terminal stops do not offer boarding.

The nightly publication imports yesterday and the following eight dates, requires a complete timetable import, validates the resulting feed, and retains the last successful snapshot if that agency fails.  Other agencies can still refresh.  The website consumes this feed through the same standard importer as Christchurch, Auckland and Wellington.  Metadata identifies it as derived and names the source; it is not labelled an official agency GTFS feed.

Location-only feeds cannot establish an authoritative timetable.  For another agency, supply a reviewed published schedule as the static source, then provide a realtime adapter with stable route/trip/stop identifiers.  History-based estimates must remain separately attributed predictions and never become official scheduled times.

Polling windows come from actual active trips, calendar additions/removals and GTFS times over 24:00, using the agency timezone and GTFS noon anchor.  Windows start 15 minutes early and finish 30 minutes after the last scheduled stop.  Gaps between windows do not trigger upstream live calls.  Outside covered dates or without valid window metadata, the website serves schedules and does not query the live API.

Whangārei's Ride Guide realtime upgrade may still be rejected by the hosted runtime.  The GTFS realtime endpoint only returns verified predictions when upstream data is available.  A compatible format does not create live access or fabricate ETAs.
