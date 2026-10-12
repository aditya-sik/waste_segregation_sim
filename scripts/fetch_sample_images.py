#!/usr/bin/env python3
"""Download sample waste images from Wikimedia Commons and write assets/samples/manifest.json.

Usage (from the project root):
    python scripts/fetch_sample_images.py                # download missing images
    python scripts/fetch_sample_images.py --force        # re-download everything
    python scripts/fetch_sample_images.py --manifest-only  # rebuild manifest from files on disk

Rules enforced:
  * Only the official Commons API is used. No Google Images, no scraping of pages.
  * Only files with permissive licences are accepted: CC0, Public domain, CC BY, CC BY-SA.
    Non-commercial (NC) and no-derivatives (ND) licences are rejected.
  * The Commons file title must contain one of the sample's title keywords, a basic
    check that the file plausibly matches its assigned category. Review the gallery visually.
  * Every download is decoded with Pillow. Invalid or tiny files are rejected.
  * Failures are recorded in the manifest and reported. Nothing is silently substituted.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Optional

import requests
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from decision_engine import CLASS_TO_BIN  # noqa: E402
from sample_data import MANIFEST_PATH, SAMPLES, SAMPLES_DIR, DemoSample  # noqa: E402

API_URL = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "WasteSegregationSimulator/1.0 (college project; educational, non-commercial use)"
MIN_SIDE_PX = 200
THUMB_WIDTH_PX = 800
REQUEST_PAUSE_S = 0.5
ALLOWED_LICENCE = re.compile(r"^(CC0|Public domain|PD-|CC BY(-SA)? \d)", re.IGNORECASE)


def strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", html.unescape(value)).strip()


def licence_allowed(licence_name: str) -> bool:
    return bool(ALLOWED_LICENCE.match(licence_name.strip()))


def is_valid_image(path: Path) -> bool:
    try:
        with Image.open(path) as img:
            img.load()
            return min(img.size) >= MIN_SIDE_PX
    except (OSError, ValueError, SyntaxError):
        return False


def find_commons_file(session: requests.Session, sample: DemoSample) -> dict:
    """Search Commons and return the first file that passes the licence and title checks."""
    params = {
        "action": "query",
        "format": "json",
        "formatversion": 2,
        "generator": "search",
        "gsrsearch": f"filetype:bitmap {sample.search_term}",
        "gsrnamespace": 6,
        "gsrlimit": 15,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|mime|size",
        "iiurlwidth": THUMB_WIDTH_PX,
    }
    response = session.get(API_URL, params=params, timeout=20)
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", [])

    for page in sorted(pages, key=lambda p: p.get("index", 0)):
        title = page.get("title", "")
        infos = page.get("imageinfo") or [{}]
        info = infos[0]
        if info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        if not any(k.lower() in title.lower() for k in sample.title_keywords):
            continue
        meta = info.get("extmetadata", {})
        licence_name = meta.get("LicenseShortName", {}).get("value", "")
        if not licence_allowed(licence_name):
            continue
        artist = strip_html(meta.get("Artist", {}).get("value", "")) or "Unknown author"
        return {
            "title": title,
            "download_url": info.get("thumburl") or info.get("url"),
            "source_url": info.get("descriptionurl", ""),
            "license": strip_html(licence_name),
            "attribution": f"{artist}, {strip_html(licence_name)}, via Wikimedia Commons",
        }
    raise LookupError("no file with a permitted licence and a matching title was found")


def fetch_sample(session: requests.Session, sample: DemoSample) -> dict:
    """Download one sample, validate it, save it as JPEG, and return its manifest fields."""
    found = find_commons_file(session, sample)
    response = session.get(found["download_url"], timeout=30)
    response.raise_for_status()

    with Image.open(BytesIO(response.content)) as img:
        img.load()
        if min(img.size) < MIN_SIDE_PX:
            raise ValueError(f"image too small ({img.size})")
        target = SAMPLES_DIR / sample.filename
        img.convert("RGB").save(target, format="JPEG", quality=90)

    if not is_valid_image(target):
        target.unlink(missing_ok=True)
        raise ValueError("saved file failed validation")

    return {
        "status": "downloaded",
        "source_url": found["source_url"],
        "license": found["license"],
        "attribution": found["attribution"],
        "commons_title": found["title"],
        "error": "",
    }


def read_previous_results() -> dict[str, dict]:
    if not MANIFEST_PATH.is_file():
        return {}
    try:
        raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {e["sample_id"]: e for e in raw.get("samples", [])}


def build_manifest(results: dict[str, dict]) -> dict:
    """Write one entry per sample. Download status reflects the file actually on disk."""
    entries = []
    for sample in SAMPLES:
        info = results.get(sample.sample_id, {})
        target = SAMPLES_DIR / sample.filename
        on_disk = target.is_file() and is_valid_image(target)
        status = "downloaded" if on_disk else "missing"
        entries.append({
            "sample_id": sample.sample_id,
            "unique_id": sample.sample_id,
            "image_file": f"assets/samples/{sample.filename}",
            "display_name": sample.display_name,
            "assigned_demo_class": sample.demo_class,
            "proposed_bin": CLASS_TO_BIN[sample.demo_class],
            "demo_confidence": sample.demo_confidence,
            "fixed_sensor_readings": {
                "ir_detected": sample.ir_detected,
                "weight_g": sample.weight_g,
                "moisture_pct": sample.moisture_pct,
                "encoder_pulses": sample.encoder_pulses,
            },
            "search_term": sample.search_term,
            "source_url": info.get("source_url", "") if on_disk else "",
            "license": info.get("license", "") if on_disk else "",
            "attribution": info.get("attribution", "") if on_disk else "",
            "commons_title": info.get("commons_title", "") if on_disk else "",
            "download_status": status,
            "error": "" if on_disk else info.get("error", "not attempted"),
        })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "Demo data only. Classifications and sensor values are predefined, not measured or model outputs.",
        "samples": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="re-download even if a valid file exists")
    parser.add_argument("--manifest-only", action="store_true", help="do not use the network")
    args = parser.parse_args()

    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    previous = read_previous_results()
    results: dict[str, dict] = {}

    if not args.manifest_only:
        session = requests.Session()
        session.headers["User-Agent"] = USER_AGENT
        network_down = False

        for sample in SAMPLES:
            target = SAMPLES_DIR / sample.filename
            if target.is_file() and not args.force and is_valid_image(target):
                results[sample.sample_id] = previous.get(sample.sample_id, {})
                print(f"[have   ] {sample.sample_id}")
                continue
            if network_down:
                results[sample.sample_id] = {"error": "skipped: network unreachable"}
                print(f"[MISSING] {sample.sample_id}: skipped, network unreachable")
                continue
            try:
                results[sample.sample_id] = fetch_sample(session, sample)
                print(f"[ok     ] {sample.sample_id}: {results[sample.sample_id]['license']}")
            except requests.ConnectionError as exc:
                network_down = True
                results[sample.sample_id] = {"error": f"network error: {exc.__class__.__name__}"}
                print(f"[MISSING] {sample.sample_id}: network error, further downloads will be skipped")
            except Exception as exc:  # report every other failure without stopping the batch
                results[sample.sample_id] = {"error": f"{exc.__class__.__name__}: {exc}"}
                print(f"[MISSING] {sample.sample_id}: {results[sample.sample_id]['error']}")
            time.sleep(REQUEST_PAUSE_S)
    else:
        results = previous

    manifest = build_manifest(results)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    missing = [e for e in manifest["samples"] if e["download_status"] != "downloaded"]
    present = len(manifest["samples"]) - len(missing)
    print()
    print(f"Images present: {present} of {len(manifest['samples'])}")
    print(f"Manifest written: {MANIFEST_PATH.relative_to(PROJECT_ROOT)}")
    if missing:
        print("\nMissing images:")
        for entry in missing:
            print(f"  - {entry['sample_id']} ({entry['display_name']}): {entry['error']}")
        print(
            "\nFallback: the dashboard still runs. Missing samples show a 'NOT DOWNLOADED' placeholder "
            "and simulate with their predefined data.\n"
            "To fix: re-run this script while online, or place a CC0/CC BY/CC BY-SA JPEG named "
            "<sample_id>.jpg in assets/samples/ and record its source and licence in the manifest."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
