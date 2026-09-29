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

    return selected


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
    for artifact in artifacts:
        target = OUTPUT_DIR / str(artifact["id"])
        if target.exists() and any(target.rglob("*.jsonl.gz")):
            continue

        download_artifact(artifact)
        downloaded += 1
        print(f"Downloaded {artifact['name']} ({artifact['id']})")

    files = list(OUTPUT_DIR.rglob("*.jsonl.gz"))
    print(f"Downloaded {downloaded} new artifacts; {len(files)} data files available.")


if __name__ == "__main__":
    main()
