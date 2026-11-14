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

Distinguish a plugged-in USB supply from a battery installation using available hardware signals or installer configuration.  A single battery-voltage reading cannot establish a sustainable solar budget.  For solar installations, use available charging telemetry or battery trend and reserve over time.  Use conservative defaults when evidence is missing.  Require sustained recovery before restoring expensive duties, and suspend them promptly if the battery reserve is threatened.  Tune thresholds against measured consumption.

Treat upstream reachability, feed freshness and radio connectivity separately.  On upstream loss, preserve the age and source of cached departures and allow a qualified peer to take over.  Keep passenger display cadence independent of network cadence.  Preserve light sleep, wake before first service, provisional clock recovery and existing schedule fallback.

## Group traffic

Provision a transit area and, where needed, a smaller service group.  Give each group an expected node count as a planning input.  Observe distinct active nodes and actual channel use to adjust reporting intervals.  Sleeping nodes can disappear from the count temporarily.  Increasing membership must not cause every device to poll every peer.  Groups sharing a radio channel also share its airtime.

Start with one active gateway per group and a standby takeover delay.  Enable relaying only where it extends coverage.  Scope packets by group, deduplicate by origin and message ID, bound forwarding by hop count and expiry, and stagger transmissions.  Give imminent service updates priority over discovery and routine status.  Gateway election, group budgets and relay protocol details require bench validation.

## First development session

1. Run the same candidate build on a headless radio node and a display-equipped node.  Verify the startup capability report and that missing peripherals do not block startup.
2. With sustained power and Wi-Fi, fetch a timetable on the headless node and deliver it over LoRa.  Repeat with the display-equipped node serving its stop and distributing the timetable concurrently.
3. Remove upstream access, simulate declining power, then restore both.  Verify duty changes, stable recovery, cached departures and the reason logged for each transition.
4. In a subsequent three-node trial, demonstrate one useful relay hop, duplicate suppression and reduced radio activity on battery.  Recheck overnight wake and first-service behaviour before moving the Museum installation to the candidate build.
