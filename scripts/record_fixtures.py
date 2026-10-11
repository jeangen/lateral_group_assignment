"""Record live World Bank API responses as test fixtures.

Run once with network access (`make record-fixtures`). Writes every page verbatim to
tests/fixtures/recorded/ plus a manifest with the URL, fetch time and sha256 of each
file, so the provenance of every fixture is auditable. Tests never call the live API;
they read these files.

Requests mirror the ingestion design (spec §9): one request for country metadata and one
request per indicator covering all configured countries and years.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "pipeline.yml"
OUT_DIR = ROOT / "tests" / "fixtures" / "recorded"


def build_requests(cfg: dict) -> list[tuple[str, str, dict]]:
    """Return (fixture_name, path, params) for every logical request."""
    scope, api = cfg["scope"], cfg["api"]
    countries = ";".join(scope["countries"])
    years = f"{scope['years']['start']}:{scope['years']['end']}"
    base = {"format": "json", "per_page": api["per_page"]}

    reqs = [("country", f"country/{countries}", dict(base))]
    for ind in scope["indicators"]:
        code = ind["code"]
        params = dict(base, date=years, source=api["source_id"])
        reqs.append((f"indicator_{code}", f"country/{countries}/indicator/{code}", params))
    return reqs


def fetch_all_pages(base_url: str, path: str, params: dict, timeout: int) -> list[tuple[str, int, bytes]]:
    """Fetch every page of one request. Returns (url, page, raw_body) per page."""
    pages, page, total_pages = [], 1, 1
    while page <= total_pages:
        resp = requests.get(f"{base_url}/{path}", params={**params, "page": page}, timeout=timeout)
        resp.raise_for_status()
        body = resp.content
        payload = json.loads(body)
        if not (isinstance(payload, list) and len(payload) == 2 and "page" in payload[0]):
            raise RuntimeError(f"Unexpected payload for {resp.url}: {body[:300]!r}")
        total_pages = int(payload[0]["pages"]) or 1
        pages.append((resp.url, page, body))
        page += 1
        time.sleep(0.2)  # be polite to a public API
    return pages


def main() -> int:
    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    api = cfg["api"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest = []
    for name, path, params in build_requests(cfg):
        for url, page, body in fetch_all_pages(api["base_url"], path, params, api["timeout_seconds"]):
            filename = f"{name}_p{page}.json"
            (OUT_DIR / filename).write_bytes(body)
            manifest.append({
                "file": filename,
                "url": url,
                "page": page,
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "sha256": hashlib.sha256(body).hexdigest(),
            })
            print(f"recorded {filename}")

    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"{len(manifest)} pages recorded to {OUT_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
