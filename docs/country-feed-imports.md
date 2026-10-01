# Country timetable imports

Address autocomplete sends the selected or IP-detected ISO country to Photon before searching (`countrycode`). Full address searches restrict Nominatim using `countrycodes`. Country changes clear old results and selections. Country source warming runs separately from address suggestions.

The site ships a fallback Transitous catalogue and reads the refreshed catalogue from the `feed-data` branch. Only the current country's sources are returned to the browser. As soon as a country is detected or selected, `/api/transit/country` checks its published index and requests `import_country_feeds.yml` if needed. Only a country code goes to GitHub; no visitor IP or address is sent. The shared D1 database lease coalesces dispatches across visitors for ten minutes.

## Activation

Create a fine-grained GitHub token scoped to **TheReverendCard/open-transit-display**, with **Actions: read and write**, and add it as repository Actions secret **GITHUB_COUNTRY_IMPORT_TOKEN**. Run the existing `Publish feed snapshots` workflow once to include it in the encrypted credential handoff. The site's existing RSA key decrypts it only on the server. The same name can alternatively be configured directly as a Site runtime secret. Never put it into client code or a public file.

Without this credential, the source catalogue and already mirrored timetables work, but visitor-triggered imports cannot run. An owner can still run the country import workflow manually, supplying an uppercase ISO country code.

## Publication and limits

The importer uses processed static ZIPs listed at https://transitous.org/sources/ and publishes them under `countries/XX/feeds/<source-id>/gtfs.zip`, alongside boarding-stop metadata. `countries/XX/index.json` records validity, freshness and geographical bounds. ZIPs are validated before publication; corrupt or unsuccessful refreshes retain the last verified snapshot.

Each job attempts at most 20 sources and downloads at most 256 MiB, with a 64 MiB limit per ZIP. Pending sources are processed before older verified files and failed sources. Larger countries require multiple jobs: later visitor dispatches continue the import; the nightly workflow also rotates through two activated countries. This limits upstream traffic and GitHub storage growth, and means a whole country is **not guaranteed ready during the first address search**. Feeds that exceed the limit or fail validation remain unavailable. Published snapshots older than eight days are not used for nearby discovery or download redirects.

Nearby discovery checks country indexes and geographical bounds before fetching boarding-stop metadata. Stops within 1.2 km are shown first; farther or unchecked sources remain in the searchable agency fallback. When an import has been queued, the page polls for nearby results every five seconds for up to three minutes, stopping when the address/country changes or an agency is selected. A pending selected source can be streamed through the server from Transitous; if that upstream source is blocked, the page explains that preparation is still pending.

This pathway is static timetable support. It does not discover or poll GTFS-RT or location feeds. Existing NZ API/live-feed integrations are kept separate, and those networks are omitted from the NZ fallback catalogue to avoid duplicate choices.

Attribution to Transitous is shown in the setup page and imported feed label. Source licences and attribution requirements remain applicable; this importer does not confer a licence to use source data commercially.
