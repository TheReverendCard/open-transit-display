# Christchurch API connection

The workflow `Import Christchurch GTFS and check live feed` uses the existing repository Actions secrets `METRO_LIVE_FEED_PRIMARY` and `METRO_LIVE_FEED_SECONDARY`.  It sends the subscription header only to the official Metro API.  HTTP 401 or 403 on the primary key triggers the secondary key; other failures are reported without exposing upstream error bodies or credentials.

Each run downloads and validates the static GTFS ZIP and a realtime trip-update snapshot, then imports seven days through the existing generic importer.  Both subscriptions must permit the requested products.  A connection summary and feed snapshots are uploaded as an Actions artifact.  The ZIP can be used in the configurator's GTFS upload test.  Runs start on importer changes or manually through Actions; this workflow is not a continuously running live backend.

GitHub Actions secrets are available to workflows, not directly to the separately hosted Sites runtime.  The website's realtime endpoint requires a runtime key or an authenticated bridge from a continuously running GitHub-managed backend.  Actions artifacts alone do not provide timely live predictions.  Never export secret values as artifacts or commit them into the repository.

Data attribution:  Environment Canterbury, CC BY 4.0.  No official affiliation is claimed.
