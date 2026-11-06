# CityLink Cloud Run metadata-only monitor

This is a **separate, private, metadata-only diagnostic collector**. It does not
operate the LoRa gateway, change the Museum sign, publish Ride Guide GTFS-RT,
or retain individual vehicle/trip records.

The Cloud Run service fetches both public static timetable inputs from the
same exact `feed-data` commit. It checks the actual Auckland service window,
then runs the existing 40-second bounded WebSocket collector **in memory**
and logs only aggregate counts, feed ages and operational counters.

## Deploy from GitHub using Google Cloud Developer Connect

1. **Before deploying**, review this code and merge this PR into `main`.
2. Cloud Run > Create service > Continuously deploy from GitHub.
3. Select `TheReverendCard/open-transit-display`, branch `main`,
   Build type **Dockerfile**, Source location **/Dockerfile** (repository root).
4. Service name `citylink-monitor`; region `australia-southeast1` (Sydney).
5. Require authentication; ingress **All**; request-based billing.
   Minimum instances **0**, maximum instances **1**, concurrency **1**,
   memory **512 MiB**, CPU **0.5 vCPU** where offered, request timeout
   **180 seconds**. Do not enable unauthenticated access.
6. Deployment only creates the listener. **No upstream collection occurs**
   unless an authenticated request POSTs to `/collect`.

## Schedule (only after deployment)

Create one **Cloud Scheduler** HTTP job calling the service's `/collect`
URL with **POST**, an **OIDC** token from a dedicated service account with
`roles/run.invoker` on the Cloud Run service, and audience set to the
service's base URL (not the /collect path).

- Frequency: `2-59/5 * * * *`
- Time zone: `Etc/UTC` (local service windows are determined separately)
- Location: `australia-southeast1`
- Retry policy: disable or keep short; retries can generate extra observations

Cron triggers are **at least once**, not guaranteed exactly once. Each log
record includes the actual start timestamp and any Scheduler nominal-time
header, enabling coverage analysis and deduplication in later reports.

The service responds to `GET /health` and `POST /collect` only. The Cloud
Run IAM restriction protects both. No public arrival, protobuf or location
endpoint exists.

## Data and cost boundaries

- Raw provider messages remain in RAM and are discarded at the end of each request.
- Public static GTFS and trip map are downloaded to a temporary directory and deleted.
- The response reports only `sampled`, `empty_snapshot`, `no_packets`,
  `skipped_outside_service`, `skipped_invalid_timetable` or `error`.
- Aggregate metrics are emitted in private **Cloud Logging** under
  `CITYLINK_MONITOR=` with service start, upstream source age, empty feeds,
  collection errors, and static-feed commit; no raw provider messages.
- Cloud Logging retention is finite and may incur costs if free allowance is exceeded.
  Add export/long-term storage only after confirming permissions and costs.
- Cloud Run, Cloud Build, Developer Connect, Artifact Registry, and Cloud
  Scheduler have independent billing dimensions. Set a budget alert before use.
  A billing budget is not a hard spending cap.

**Build only**: Cloud Run cannot collect anything until you create the
authenticated Scheduler job (or manually invoke the private endpoint).
