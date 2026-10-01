# Country timetable imports

Address autocomplete restricts Photon with `countrycode`; full searches restrict Nominatim with `countrycodes`. Country changes clear old addresses and agency selections. An empty address result names the country searched so visitors can correct a VPN or country selection.

The site reads a refreshed Transitous catalogue from `feed-data`, with a bundled fallback. Only the selected country's sources reach the browser. Country detection or selection can warm its snapshots in the background. Selecting an uncached local source from the normal agency list requests the same workflow, prioritising that source. Requests send only country and optional published source ID to GitHub, never visitor IP or address. D1 leases coalesce requests for each country/source for ten minutes.

## Activation

Create a fine-grained token scoped to **TheReverendCard/open-transit-display**, with **Actions: read and write**, and add it as Actions secret **COUNTRY_IMPORT_TOKEN**. Run **Publish nightly timetable snapshots for the website** once to include it in the encrypted credential handoff. The existing RSA key decrypts it only on the server. The workflow maps this allowed repository secret name to the internal `GITHUB_COUNTRY_IMPORT_TOKEN` credential. Alternatively configure `GITHUB_COUNTRY_IMPORT_TOKEN` directly as a Site runtime secret. Never put credentials into client code or public files.

Without this credential, source discovery and mirrored timetables work, but visitor-triggered imports cannot start. The page reports that failure without displaying a countdown. Owners can run **Import country timetable snapshots** manually, supplying an uppercase ISO country and optional source ID.

## Agency discovery

Fresh boarding-stop metadata provides exact nearest-stop distances and the 1.2 km walking filter. When a timetable is not cached, a known source service area can put it in the normal agency list as pending. This does not claim a verified nearby stop. The `mx_mexico` source is labelled **Mexico City public transport (SEMOVI)** using the publisher at https://datos.cdmx.gob.mx/dataset/gtfs and a Mexico City geographical hint. Otherwise, sources without geographical evidence remain in **Can't find your agency?**, labelled as unchecked country-wide sources. Geographic hints do not replace boarding-stop metadata once imported.

After GitHub accepts an import, the interface suggests refreshing in **about five minutes**, explicitly an estimate affected by feed size and queue time. It checks for results every five seconds for up to three minutes while the address is unchanged and no agency has been selected. A failed or unavailable import never shows a success countdown.

## Publication and limits

The collector validates processed static ZIPs listed at https://transitous.org/sources/ before publishing `countries/XX/feeds/<source-id>/gtfs.zip`, boarding-stop metadata and `countries/XX/index.json` on `feed-data`. Failed refreshes preserve the last verified file. Each job attempts up to 20 sources and downloads up to 256 MiB, with a 64 MiB limit per ZIP. An explicitly selected source is attempted first, then pending sources, oldest verified feeds, and failed sources. Large countries need multiple jobs. Nightly updates rotate through two activated countries; visitor requests continue incomplete imports. Snapshots older than eight days are not used for nearby discovery or download redirects.

This is static timetable support. International realtime connections require a separate provider registry for endpoint, format, credentials, licence/access requirements and polling limits, using shared network caches rather than per-display upstream polling. No international live feeds are automatically discovered or polled by this importer. Existing NZ live connections are preserved and those networks are omitted from the NZ fallback catalogue to avoid duplicate choices.

Transitous attribution is shown in setup and the imported feed label. Source licensing and attribution requirements continue to apply.
