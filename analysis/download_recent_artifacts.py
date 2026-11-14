import io
import os
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests


REPOSITORY = os.environ.get("GITHUB_REPOSITORY")
TOKEN = os.environ.get("GITHUB_TOKEN")
DAYS = int(os.environ.get("ARTIFACT_DAYS", "14"))
OUTPUT_DIR = Path(os.environ.get("ARTIFACT_OUTPUT_DIR", "data/artifacts"))
MAX_ARTIFACTS = int(os.environ.get("ARTIFACT_MAX_COUNT", "0"))
ALLOW_PARTIAL = os.environ.get("ARTIFACT_ALLOW_PARTIAL", "false").lower() == "true"


def github_headers():
    if not TOKEN:
        raise RuntimeError("GITHUB_TOKEN is required")
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def parse_github_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def list_recent_artifacts():
    if not REPOSITORY:
        raise RuntimeError("GITHUB_REPOSITORY is required")

    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS)
    headers = github_headers()
    page = 1
    selected = []

    while True:
        url = f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts"
        response = requests.get(
            url,
            headers=headers,
            params={"per_page": 100, "page": page},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        artifacts = payload.get("artifacts", [])

        if not artifacts:
            break

        stop_paging = False
        for artifact in artifacts:
            created_at = parse_github_time(artifact["created_at"])
            if created_at < cutoff:
                stop_paging = True
                continue

            if artifact.get("expired"):
                continue

            if not artifact.get("name", "").startswith("collector-"):
                continue

            selected.append(artifact)

        if stop_paging or len(artifacts) < 100:
            break

        page += 1

    selected.sort(key=lambda artifact: parse_github_time(artifact["created_at"]), reverse=True)
    return selected[:MAX_ARTIFACTS] if MAX_ARTIFACTS > 0 else selected


def download_artifact(artifact):
    headers = github_headers()
    response = requests.get(
        artifact["archive_download_url"],
        headers=headers,
        timeout=120,
    )
    response.raise_for_status()

    artifact_dir = OUTPUT_DIR / str(artifact["id"])
    artifact_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        archive.extractall(artifact_dir)

    return artifact_dir


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    artifacts = list_recent_artifacts()
    print(f"Found {len(artifacts)} collector artifacts from the last {DAYS} days.")

    downloaded = 0
    skipped = []
    for artifact in artifacts:
        target = OUTPUT_DIR / str(artifact["id"])
        if target.exists() and any(target.rglob("*.jsonl.gz")):
            continue

        try:
            download_artifact(artifact)
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if not ALLOW_PARTIAL or status not in (404, 410, 429, 500, 502, 503, 504):
                raise
            skipped.append({"id": artifact["id"], "name": artifact["name"], "status": status})
            # Avoid logging HTTPError strings containing signed storage URLs.
            print(f"::warning::Collector artifact {artifact['id']} unavailable (HTTP {status}); comparison coverage is partial.")
            continue
        downloaded += 1
        print(f"Downloaded {artifact['name']} ({artifact['id']})")

    files = list(OUTPUT_DIR.rglob("*.jsonl.gz"))
    print(f"Downloaded {downloaded} new artifacts; {len(files)} data files available.")
    import json
    report = {
        "days": DAYS,
        "max_artifacts": MAX_ARTIFACTS,
        "selected_artifacts": len(artifacts),
        "downloaded_artifacts": downloaded,
        "data_files": len(files),
        "skipped_artifacts": skipped,
        "partial": bool(skipped),
    }
    (OUTPUT_DIR / "download_summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if ALLOW_PARTIAL and not files:
        raise RuntimeError("No collector data available; comparison cannot run.")


if __name__ == "__main__":
    main()
