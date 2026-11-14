# Unified node firmware

## Direction agreed 14 November 2026

Develop one firmware for supported node configurations.  Display, gateway and relay are duties that a device can combine or suspend at runtime.  The standalone gateway timetable trial proposed in issue #10 becomes the first gateway test of this shared firmware.  This document records the design direction.  The adaptive duties and policies below are proposed work.  The Museum sign running v0.8.4e is the field baseline.

| Available resources | Eligible duties |
| --- | --- |
| Sustained power, working Wi-Fi upstream, LoRa | Fetch and distribute transit updates as a gateway. |
| The above plus a display | Also show departures for the configured stop. |
| Sustainable solar and battery, LoRa, no working upstream | Receive and, if needed, relay updates within the configured group.  A fitted display serves its stop. |
| Limited battery, LoRa | Prefer receiving updates for the local stop.  Reduce radio activity, suspend routine forwarding and use the cached timetable between updates. |
| Display, no usable network | Show the cached timetable when the clock and schedule coverage allow it.  Indicate when the time is provisional. |

## Setup and duty changes

Use a supported board profile to select safe peripheral pins.  Probe what can be detected reliably.  Ask once for ambiguous hardware or installation details, including power arrangement, display model if needed, Wi-Fi credentials, transit group and local stop if applicable.  Retain those settings across restarts.  Report the detected capabilities, current duties and the reason for each change.

Distinguish a plugged-in USB supply from a battery installation using available hardware signals or installer configuration.  A single battery-voltage reading cannot establish a sustainable solar budget.  For solar installations, use available charging telemetry or battery trend and reserve over time.  Use conservative defaults when evidence is missing.  Require sustained recovery before restoring expensive duties, and suspend them promptly if the battery reserve is threatened.  Take battery samples during existing wake periods under comparable load.  Start with an hourly trend to detect depletion and a daily comparison of pre-dawn reserves to assess whether a duty is sustainable.  Continue immediate low-reserve protection between trend decisions.  Tune thresholds against measured consumption.

Treat upstream reachability, feed freshness and radio connectivity separately.  On upstream loss, preserve the age and source of cached departures and allow a qualified peer to take over.  Keep passenger display cadence independent of network cadence.  Preserve light sleep, wake before first service, provisional clock recovery and existing schedule fallback.

## Stop-to-stop forwarding and radio windows

A group is a set of stops that can exchange relevant transit data over LoRa, including when no internet gateway is reachable.  Any capable sign can forward for another stop.  One Wi-Fi gateway can inject fresh data for the entire corridor.  With the gateway absent, peers can still exchange cached timetable revisions and unexpired predictions with their original timestamps.  Transit area and route scope limit which traffic should cross a link.  Expected device count informs capacity planning.

Start with fixed forwarding assignments based on measured reception.  Where one broadcast reaches several stops, let all consume it and select only the sign needed to reach the next uncovered stops.  Prefer the path expected to use the least airtime including retries.  Reuse assignments until repeated delivery failures or a power change justify repair.  Identify updates by origin and sequence, suppress duplicates, and enforce expiry and a hop limit.

Use a repeating timetable of radio windows that persists across gateway loss.  The upstream sign sends first, with each downstream forwarding slot following its receive slot in the same cycle.  Reserve a short, bounded repair window.  Use guard time for measured clock drift and an infrequent rendezvous window for startup or missed synchronisation.  Peers can maintain relative slot timing while the gateway is away.  Treat passenger clock accuracy separately.  Sleep the radio and processor between required windows where display work permits.

* Live service: send a compact trip update with the source time and affected stops' predictions.  Include a vehicle position once per update if needed.  Generate countdowns locally.  Send on a material prediction or service-state change and at a bounded freshness interval while the source remains live.  Discard superseded updates before forwarding.
* Timetable: advertise revision and coverage in a normal window.  Transfer changed or missing pages in spare slots.  Coalesce missing-page requests, cap retries, and activate a revision after all required pages validate.  Keep serving the previous valid schedule during repair.
* Health: piggyback delivery progress and capability changes where possible.  Avoid per-stop acknowledgements for every group broadcast.  Keep quiet periods sparse and retain the independent first-service wake.

Choose slot lengths and cadence from measured packet airtime, clock drift, processing time, delivery reliability and the acceptable age at the furthest stop.  Record transmissions per delivered update, age at the last stop, missed updates and radio awake time.  A single lost packet should be recoverable within a bounded window without redistributing the whole timetable.  This design uses MeshCore as a reference for peer communication.  Selection of a wire protocol and interoperability remain open.

## First development session

1. Run the same candidate build on a headless radio node and a display-equipped node.  Verify the startup capability report and that missing peripherals do not block startup.
2. With sustained power and Wi-Fi, fetch a timetable on the headless node and deliver it over LoRa.  Repeat with the display-equipped node serving its stop and distributing the timetable concurrently.
3. Remove upstream access, simulate declining power, then restore both.  Verify duty changes, stable recovery, cached departures and the reason logged for each transition.
4. In a subsequent three-node trial, demonstrate one useful relay hop, duplicate suppression and reduced radio activity on battery.  Recheck overnight wake and first-service behaviour before moving the Museum installation to the candidate build.
