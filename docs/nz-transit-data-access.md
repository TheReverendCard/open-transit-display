# New Zealand transit data access

Checked 1 October 2026. One row per transport authority or jointly managed network, rather than one row per city or bus contractor. Static feeds are timetable data, not verified realtime access. A passenger tracking website does not establish public developer API access.

| Agency / network | Access link | Status |
| --- | --- | --- |
| Auckland Transport | [Developer portal](https://dev-portal.at.govt.nz/) | Existing integration. Account/key for realtime; static ZIP is public. |
| Environment Canterbury / Metro | [Developer signup](https://apidevelopers.metroinfo.co.nz/signup) | Existing integration using registered keys. |
| Greater Wellington / Metlink | [Developer portal](https://opendata.metlink.org.nz/) | Existing integration. Account/key for realtime; static ZIP is public. |
| Northland Regional Council / CityLink | [Transport team](https://www.nrc.govt.nz/transport/) | Existing derived timetable integration. No public developer signup verified; Ride Guide realtime currently returns HTTP 403 from hosted runtime. |
| Waikato Regional Council / BUSIT | [Official feed information](https://www.busit.co.nz/using-the-bus/transit-app/) · [GTFS ZIP](https://wrcscheduledata.blob.core.windows.net/wrcgtfs/busit-nz-public.zip) | Public static GTFS integrated; no account required. Ask council for realtime access. |
| Bay of Plenty Regional Council / Baybus | [Official GTFS page](https://www.baybus.co.nz/help-and-contact/general-transit-feed-specification) | Public static GTFS integrated for Tauranga, Rotorua, Whakatāne and rural services; no account required. |
| Taranaki Regional Council / Taranaki Buses | [GTFS ZIP from publisher](https://data.trilliumtransit.com/gtfs/trc-nz/trc-nz.zip) · [Council transport](https://www.trc.govt.nz/buses-transport/) | Public static GTFS integrated; no account required. Ask council for realtime access. |
| Nelson City Council and Tasman District Council / eBus | [GTFS ZIP from publisher](https://data.trilliumtransit.com/gtfs/nsn-nz/nsn-nz.zip) · [Contact](https://ebus.nz/using-ebus/contact-us/) | Public static GTFS integrated; no account required. One joint network. |
| Otago Regional Council / Orbus | [Official GTFS and terms](https://www.orc.govt.nz/privacy-and-tscs#general-transit-feed-specification-gtfs) | Public static GTFS integrated for Dunedin and Queenstown; no account required. |
| Horizons Regional Council / Connect | [Contact](https://www.goconnect.org.nz/contact-us) | Supplied GTFS URL still returns HTTP 404 from the collector. Current static URL requested by email. Horizons replied that its GTFS-RT is managed by a third party and is not made public. |
| Hawke’s Bay Regional Council / goBay | [Official GTFS page](https://www.gobay.co.nz/general-transit-feed-specification/) · [GTFS ZIP](https://www.gobay.co.nz/assets/HBRC-GTFS-January-2026.zip) | Public static GTFS integrated; no account required. Realtime access requested by email. |
| Gisborne District Council / GizzyBus and Waka Kura | [Bus services](https://www.gdc.govt.nz/services/bus-services) · [Contact](https://www.gdc.govt.nz/council/contact-us) | Live passenger maps available; no public developer signup or downloadable GTFS verified. Access requested by email. Public map endpoint discovery is a future fallback if declined. |
| Marlborough District Council | [Bus services](https://www.marlborough.govt.nz/services/bus-services) · [Contact](https://www.marlborough.govt.nz/contact-us) | Public route/stop GIS is available, but no complete downloadable GTFS or developer signup verified. Request timetable feed. |
| Invercargill City Council / BusSmart | [Buses and contact](https://www.icc.govt.nz/services/buses) | Passenger Ride Guide links are available; no public developer signup or GTFS download verified. Request feed access. |

Shared supplier: [Dynamis / Radiola API information](https://dynamis.live/integrations) and [contact](https://dynamis.live/contact). The supplier advertises GTFS and GTFS-Realtime integrations, but does not provide a verified self-service developer registration portal. Each network’s access needs confirmation.

## Implementation

The six new public feeds are downloaded and validated in the existing nightly GitHub Actions publication workflow. Valid snapshots and boarding-stop coordinates are served from the feed-data branch. The website checks actual boarding points within 10 km after address selection, reuses the shared GTFS worker, and presents matching network identities once even where GTFS has several contractor IDs. New connections remain scheduled-only and make no realtime API requests.

Horizons’ old URL: https://www.horizons.govt.nz/HRC/media/Data/files/tranzit/HRC_GTFS_Production.zip

## Horizons public map investigation

The official Connect site links to https://horizons.dynamis.live/. Its public web client uses `/api/stops`, `/api/routes`, `/api/trips`, `/api/stops/{stop_id}/predictions`, `/api/routes/{route_id}/vehicles`, and `/api/routes/{route_id}/timetable/{date}`. Stops, routes and trips returned HTTP 200 without credentials. A prediction request for stop `32111188` also returned HTTP 200, with route/trip/stop identifiers and epoch departure times. All three sampled predictions had `schedule_based: true`; realtime predictions have not yet been verified. Vehicle and dated timetable endpoints are discovered from the public client but not yet validated. These are passenger website endpoints, not a confirmed supported developer contract. No recurring polling or Horizons integration has been enabled. Request the current GTFS URL, GTFS-Realtime access and acceptable polling rates in the pending correspondence.

## Transitous source comparison, 1 October 2026

Transitous (https://transitous.org/sources/) provides original source links and processed GTFS downloads, as well as a separate journey-planning API. Its API usage policy (https://transitous.org/api/) requires open-source, noncommercial, light usage, source attribution, contact details in User-Agent, and prior discussion for substantial traffic. It cannot provide missing coverage or realtime where its upstream supplies only schedules.

The uploaded HBRC-GTFS-January-2026.zip is byte-for-byte identical to the goBay source already integrated (470150 bytes, SHA256 d3062bd1183500dda46a209a9d4e6f47832ca29886eaae7d801356ca14d72a4d). Direct goBay and GitHub Actions downloads succeeded. It contains 11 routes, 514 stops and 352 trips. Transitous's processed goBay feed (https://api.transitous.org/gtfs/nz-hkb_goBay.gtfs.zip) and its linked publisher source (https://data.trilliumtransit.com/gtfs/hbrc-nz/hbrc-nz.zip) each contain 9 routes, 498 stops and 335 trips, with different calendars. Routes 6A and 7A exist only in the uploaded/currently integrated source. The datasets are not interchangeable without comparison; retain the existing goBay source pending council confirmation.

Horizons's processed snapshot https://api.transitous.org/gtfs/nz-mwt_Horizons-Regional-Council.gtfs.zip downloaded successfully and contains 51 routes, 739 stops, 1621 trips, with scheduled service in the next ten days. Transitous reports upstream last updated 8 July 2026; the linked original remains the same failing Horizons URL. This is a candidate fallback, not yet integrated or verified against current operator timetables. No realtime source is listed for Horizons or goBay in Transitous.

CityLink Whangarei has a downloadable publisher GTFS https://data.trilliumtransit.com/gtfs/nrc-nz/nrc-nz.zip (9 routes, 354 stops, 166 trips, service calendars through July 2027). Evaluate it against the existing derived feed before switching, particularly trip IDs used for realtime matching. Transitous also lists Bus Smart Invercargill. Marlborough and Gisborne do not appear in its New Zealand source list.

Marlborough's DataPublic/Transport MapServer layers were inspected: bus stops (71), North Route (72), South Route (73), Blenheim–Picton (74) are static geography. No vehicle, prediction, delay or trip-time fields and no timeInfo were found. Useful for stop/route geometry, not a complete timetable or realtime feed.

## Horizons vehicle endpoint confirmation

On 1 October 2026 Horizons replied that GTFS-RT feeds are managed by a third-party provider and are not made public by the council. The passenger web map remains separately accessible. Jesse supplied a successful browser request to `/api/trips/105065/vehicle`; a normal request without cookies, credentials or browser-header impersonation also returned HTTP 200. The result includes timestamped latitude/longitude, speed, heading, tripId, routeId, nextStopId and `scheduleAdherance`. A position timestamp advanced between the supplied sample and the verification request. This confirms a working vehicle observation endpoint, not a supported public GTFS-RT contract. The units/sign semantics of `scheduleAdherance` have not been validated; do not turn it into an ETA until checked against stop predictions and GTFS. Discard driver identifiers when implementing a transit adapter. No recurring collector has been enabled.
