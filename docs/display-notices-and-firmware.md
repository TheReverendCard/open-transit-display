# Secure display notices and firmware preparation

Status: reference foundation, not a deployed alert service. No official emergency
provider, mail service, production signing key, radio adapter or panel is enabled.
The hosted layout editor is a separate checkout and is unchanged by this work.

## Implemented and prepared

| Component | Status |
| --- | --- |
| Ed25519 notice verification, scoped authority grants, expiry | Tested Python implementation |
| Durable revision/cancellation protection | Tested SQLite implementation |
| GTFS-RT scope matching and validity | Tested; RideGuide collector preserves selectors and times |
| Stop snapshot comparison and private owner outbox | Tested reference functions; importer hook pending |
| Alternation, five-minute arrival rule, critical takeover | Tested Python and portable C++ policy |
| Pi/Linux receiver | Local-file verifier and JSON display-plan CLI; panel renderer pending |
| ESP32 / ESP32-S3 | PlatformIO compile scaffolds; integration and hardware tests pending |
| Meshtastic / MeshCore | Separate adapter contracts; transport implementations pending |
| Web/device HTTP routes | Contract below; not live endpoints |

## Data flow

1. An allowlisted agency adapter fetches its GTFS-RT Service Alerts over HTTPS.
   Its server-held API key never goes to a sign or public GitHub branch.
2. Preserve `informed_entity`, `active_period`, translations, source URL and effect.
   Match feed namespace first; AND fields inside one selector, OR selectors.
   Match actual stop/route/trip/direction/date contexts rather than independent
   route and trip arrays. Unsupported selectors fail closed until supported.
3. A normaliser produces public notices for matching display groups. Agency
   service notices cannot become emergency takeovers just because their text
   contains "emergency". A separately enrolled emergency authority supplies those.
4. The private signer issues short-lived, individually scoped envelopes. An
   internet gateway or either mesh adapter transports the same signed bytes.
5. Each sign verifies locally, persists the newest revision, and renders its saved
   layout with the accepted notice. Transport encryption does not confer authority.

### Agency changes and owner notifications

Recognise structured effects such as `STOP_MOVED`, `NO_SERVICE`, `DETOUR`,
`MODIFIED_SERVICE` and `ACCESSIBILITY_ISSUE` when supplied. Show the agency's
wording and source, including future effective dates. `NO_SERVICE` does not prove
permanent discontinuation. Never silently choose a replacement stop.

Compare successive complete, validated GTFS snapshots. A coordinate change of
50 metres or more creates a review candidate; a missing stop creates a missing
stop candidate. Coordinate corrections and changed IDs are possible, so these
are not asserted as confirmed moves. Feed failure or a partial import must never
generate disappearance events. Route removals require an equivalent review path.

Private storage links owner ID -> device ID -> feed ID -> stop ID -> selected
routes. The prototype `Store.subscribe` and outbox implement that relationship.
The public sign receives no owner identity or contact details. For website
integration, copy the schema into private application storage, enforce ownership
from authenticated sessions, and keep contacts in a separate account table.

Registration should offer optional verified email or push delivery and explain
that unregistered/offline downloads cannot receive owner notifications. The
authenticated owner inbox is the durable record. An explicit stop-move event or
validated snapshot candidate creates one inbox/outbox event per affected device;
deduplicate by provider + event + revision (or old/new snapshot hashes + stop).
Notify all subscribed owners, not the creator of a shared gallery layout.

Delivery worker requirements: verified destination, opt-in preference, bounded
retries with backoff, provider idempotency key, delivery status, and unsubscribe.
Do not put email addresses in GitHub, mesh messages or gallery templates. The
reference outbox queues events only; no emails or push messages are sent.

## Default display behaviour

- Emergency reception enabled, but no authority trusted until provisioned.
- Warning/info emergency: if next departure is 0–300 seconds away, keep transit
  visible with an emergency banner. Otherwise alternate 30-second emergency and
  transit-with-banner pages. Unknown/no next departure also alternates.
- Critical emergency: full emergency page regardless of arrival time.
- Every alert page includes source, issued time and "Valid until" time. Use local
  timezone for display, UTC internally. Show test messages only in explicit test
  mode with a persistent TEST label; production accepts no development keys.
- Default maximum signed lifetime: one hour; refresh active notices approximately
  every ten minutes with increasing revision numbers. Underlying agency notices
  may last days; renewed envelopes preserve their original agency issue time in
  displayed text. A refresh must never outlive an agency's actual validity period.
- Finite upstream periods are preserved. Indefinite upstream alerts get a bounded
  lease, renewed only after successful fresh retrieval. Failed fetches do not
  renew leases. Handle upstream cancellations/deletions and full versus
  differential GTFS-RT semantics explicitly.
- At expiry, remove from rotation and return to transit. Retain replay tombstones;
  do not delete cancellation revisions merely because the alert expired.
- Timer wake must occur by expiry even offline. On unknown time after reboot,
  fall back to timetable/status, not an unvalidated cached warning. Backed RTC or
  authenticated time provisioning is required before alert acceptance.
- E-paper holds an image with no power. Software cannot clear a dead battery's
  last screen: printed expiry is essential. Reserve energy for expiry/low-battery
  redraw; verify this on each panel and battery combination.
- Sleep trades emergency latency for battery life. A sleeping radio cannot hear
  notices. Installer must expose receive cadence and expected worst-case delay;
  continuous receive is a mains/high-power profile, not a universal default.

## Signed envelope and trust

`device_service/notices.py` is the normative reference for v1 validation.
Envelope contains Base64 `payload` and `signature`. Signature is Ed25519 over
ASCII `OTD-NOTICE-V1` followed by a NUL byte and the exact UTF-8 payload bytes.
Never parse and reserialise before checking the signature. Duplicate JSON keys,
unknown fields, excessive sizes, unsupported versions and invalid times reject.

Payload contains version, key_id, id, revision, kind, group, issued_at, starts_at,
expires_at, action (upsert/cancel), severity (info/warning/critical), source and
plain text. No HTML, executable commands, URLs to fetch, firmware or settings
changes are permitted in this notice message type.

Trust grant binds one key to explicit kinds and group IDs, maximum lifetime and
revocation state. Groups can represent a device, stop, route, agency, region or
country, but their membership is provisioned privately. An arbitrary broadcaster
cannot define groups for a sign. Geographical polygon matching happens at the
trusted backend; the selected membership and scope are checked on the device.

Production prerequisites: owner-authenticated enrollment with physical device
proof, pinned root/authority grants, distinct development/production keys, secure
private signing service, audit log, rate limits, key rotation and revocation.
Revocation must reach offline nodes; short leases bound but do not eliminate that
delay. Key replacement is a separately authenticated provisioning action, never a
normal mesh message. Persist replay state atomically and monitor clock rollback.
New signing keys use a fresh key_id; cancellation by a different authority requires
an explicitly delegated root operation (not implemented in this prototype).

Notice authentication does not secure firmware by itself. Production ESP32
releases need board-specific signed update/rollback controls and a reviewed secure
boot/flash-encryption provisioning process. Do not burn irreversible eFuses from
the website installer. Pi hosts need restricted service users, protected config,
signed releases and OS update maintenance. Physical access remains in scope.

## Routing contracts for website integration

These are proposed routes, not live handlers. Enforce authentication and ownership
server-side; owner IDs in submitted JSON are never sufficient. Device credentials
are unique, revocable, stored hashed server-side and excluded from shared designs.

| Route | Authorisation | Purpose |
| --- | --- | --- |
| `POST /api/devices/enrol` | Owner session + one-time physical pairing proof | Bind a new device to owner; issue a scoped device credential |
| `PUT /api/devices/{id}/subscription` | Owning session | Set feed, stop, routes, notice preferences and scope |
| `GET /api/devices/{id}/bundle` | Device credential scoped to id | Return signed transit/notice envelopes and versioned layout |
| `POST /api/devices/{id}/receipts` | Device credential scoped to id | Report received/rendered revision, battery and status |
| `GET /api/me/notifications` | Owner session | Private stop/service change inbox |
| `PUT /api/me/notification-preferences` | Owner session | Verified contact and delivery preferences |
| `POST /internal/notices/ingest/{provider}` | Provider-specific service credential | Validate, normalise and queue allowlisted feed notices |
| `POST /internal/emergencies` | Enrolled emergency publisher, scoped role, audit | Issue/revise/cancel an authenticated emergency |

Use CSRF protection for session writes, input/size/rate limits, idempotency keys,
and no credentials in URLs. A receipt describes device state only, not human
acknowledgement. Public transport adapters may relay opaque signed envelopes but
must never obtain authority signing keys. Do not expose a generic public signer.

## Radio adapters

Choose Meshtastic OR MeshCore per radio. Default display role is leaf/endpoint;
gateway/repeater roles are explicit and depend on power and firmware capabilities.
For initial Pi development, use a USB serial companion running upstream firmware.
For ESP32, begin with a serial companion or carefully integrated upstream library;
avoid assuming a custom display binary is also a compatible mesh node.

Adapter contract: `receive(bytes) -> bounded envelope`,
`send(group, bytes, priority)`, `link_status()` and optional delivery callbacks.
Use upstream application interfaces, not unauthenticated channel text commands.
Prevent Wi-Fi/mesh echo loops using envelope hash and origin cache.

V1 JSON payloads are up to 4096 bytes, NOT one LoRa packet. Before radio activation,
implement bounded fragmentation/reassembly or a smaller signed binary revision.
Set limits for fragment count, incomplete assemblies, per-peer memory, total
airtime, retry count and timeout. Verify the complete signed message before use.
Use transport-specific MTUs and airtime rules; prioritise cancellation and urgent
updates, coalesce transit changes, and jitter device receipts. Never transfer
screen bitmaps, full GTFS or firmware by routine LoRa broadcast.

## Board and upstream sources

| Target | Source and integration choice |
| --- | --- |
| ESP32 / ESP32-S3 | PlatformIO Arduino scaffolds in `firmware/esp32`; production security via [ESP-IDF](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/security/secure-boot-v2.html) |
| SPI e-paper panels | [GxEPD2](https://github.com/ZinggJM/GxEPD2); match exact controller, revision and pins |
| Waveshare ESP32 board | [Manufacturer manual](https://www.waveshare.com/wiki/E-Paper_ESP32_Driver_Board) and GxEPD2_WS_ESP32_Driver example |
| Raspberry Pi Zero 2 W / Pi 3–5 | Python receiver here; [Waveshare drivers](https://github.com/waveshare/e-Paper) or a selected image renderer |
| Meshtastic companion | [Upstream firmware](https://github.com/meshtastic/firmware) and [Python API](https://github.com/meshtastic/python) |
| MeshCore companion | [Upstream source and API links](https://github.com/meshcore-dev/MeshCore) |
| Arduino Ed25519 integration candidate | [rweather Crypto](https://github.com/rweather/arduinolibs); review/pin and verify cross-language test vectors before integration |

Screen diagonal and resolution do not identify a driver. Exact panel revision,
driver board, GPIO mapping, voltage, RAM and radio wiring must be checked before
enabling an installable profile. ESP32 boards and Raspberry Pis do not acquire
LoRa through a firmware option alone; a compatible radio is required. Keep
upstream code as pinned dependencies and preserve its licence; do not copy whole
firmware trees into this repository. The TRMNL profile needs its existing
firmware source and hardware revision confirmed before integration.

## Build and next integration gates

```sh
pip install -r device_service/requirements.txt gtfs-realtime-bindings websockets
python -m unittest discover -s tests/device_service -v
g++ -std=c++17 -Wall -Wextra -Werror firmware/shared/policy_test.cpp -o /tmp/policy-test
/tmp/policy-test
pip install platformio==6.1.18
pio run -d firmware/esp32
python -m firmware.raspberry_pi.receiver --help
```

The GitHub workflow runs policy tests and both ESP32 compile targets with read-only
permissions and no secrets. It deliberately does not publish flashable releases.

Next gates, in order: provision a development authority; wire provider adapter and
private subscription API; choose one exact panel/board; complete panel and radio
adapters; verify signed cross-language packets; exercise expiry, reboot, missing
RTC, replay, revocation, radio outage and low battery on hardware; review firmware
update security; then offer supported release manifests in the website installer.
GitHub Actions is for builds and snapshot processing, not time-critical emergency
delivery. Use an always-running service/gateway for actual alerts.

Reference: [GTFS-RT specification](https://gtfs.org/documentation/realtime/reference/).
