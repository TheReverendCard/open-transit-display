# Auckland and Wellington feed checks

The `Check AT and Metlink GTFS feeds` GitHub Actions workflow reads the existing repository secrets:

- Auckland: `AUCKLAND_TRANSPORT_PRIMARY`, then `AUCKLAND_TRANSPORT_SECONDARY` on HTTP 401 or 403.
- Wellington: `METLINK`, sent in the `x-api-key` header.

Static ZIPs are public and receive no authentication headers.  Authenticated realtime requests refuse redirects to avoid forwarding credentials.  The collector accepts standard realtime protobuf and standard GTFS realtime JSON, including the AT legacy response envelope, and stores validated protobuf snapshots.  Keys never appear in artifacts or browser code.

Auckland's generic importer test covers routes 18, 70 and NX1; Wellington's imports all routes.  The original full ZIP is preserved for each provider.  Connection reports give source table counts and realtime entity counts.  One provider's failure does not cancel the other's check.  This is a GitHub importer and API compatibility check, not a continuous live backend for the hosted configurator.  The separate website still needs a runtime feed bridge.

Sources:

- https://dev-portal.at.govt.nz/realtime-api
- https://dev-portal.at.govt.nz/
- https://www.metlink.org.nz/legal/general-transit-feed-specification
- https://opendata.metlink.org.nz/
