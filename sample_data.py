"""Predefined demonstration data for the sample waste images.

IMPORTANT: every value in this file is FIXED, ILLUSTRATIVE demo data.
  * The demo classifications are NOT outputs of a trained model.
  * The sensor values are NOT measurements from physical hardware.

This file is the single source of truth for demo values. The manifest at
assets/samples/manifest.json is generated from it by
scripts/fetch_sample_images.py, which also records image download results.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SAMPLES_DIR = PROJECT_ROOT / "assets" / "samples"
MANIFEST_PATH = SAMPLES_DIR / "manifest.json"


@dataclass(frozen=True)
class DemoSample:
    """One sample image together with its predefined demo data."""

    sample_id: str
    display_name: str
    demo_class: str            # "Organic" or "Recyclable" (predefined)
    demo_confidence: float     # 0.0-1.0, predefined -- NOT measured model confidence
    weight_g: float            # fixed HX711 reading
    moisture_pct: float        # fixed soil-moisture reading, 0-100
    ir_detected: bool          # fixed IR reading
    encoder_pulses: int        # fixed optical-encoder pulse count
    search_term: str           # query used by the fetch script on Wikimedia Commons
    title_keywords: tuple[str, ...]  # at least one must appear in the Commons file title

    @property
    def filename(self) -> str:
        return f"{self.sample_id}.jpg"


SAMPLES: tuple[DemoSample, ...] = (
    # ---- Organic (8) -------------------------------------------------------
    DemoSample("banana_peel", "Banana Peel", "Organic", 0.94, 125, 82, True, 120,
               "banana peel", ("banana",)),
    DemoSample("apple_core", "Apple Core", "Organic", 0.92, 95, 78, True, 110,
               "apple core", ("apple",)),
    DemoSample("vegetable_waste", "Vegetable Waste", "Organic", 0.89, 140, 85, True, 115,
               "vegetable scraps", ("vegetable", "vegetables")),
    DemoSample("orange_peel", "Orange Peel (Fruit Waste)", "Organic", 0.93, 88, 76, True, 105,
               "orange peel", ("orange", "peel")),
    DemoSample("fallen_leaves", "Fallen Leaves", "Organic", 0.84, 40, 45, True, 70,
               "fallen leaves", ("leaf", "leaves")),
    DemoSample("coffee_grounds", "Coffee Grounds", "Organic", 0.87, 55, 58, True, 80,
               "coffee grounds", ("coffee",)),
    DemoSample("food_scraps", "Mixed Food Scraps", "Organic", 0.91, 160, 80, True, 130,
               "food scraps", ("food", "scrap", "scraps")),
    DemoSample("bread_scraps", "Bread Scraps", "Organic", 0.88, 70, 42, True, 90,
               "bread", ("bread",)),

    # ---- Recyclable (8) ----------------------------------------------------
    DemoSample("plastic_bottle", "Plastic Bottle", "Recyclable", 0.91, 28, 12, True, 95,
               "plastic bottle", ("plastic", "bottle")),
    DemoSample("cardboard_box", "Cardboard Box", "Recyclable", 0.93, 110, 8, True, 150,
               "cardboard box", ("cardboard", "box")),
    DemoSample("newspaper", "Newspaper", "Recyclable", 0.90, 45, 6, True, 70,
               "newspaper", ("newspaper", "news")),
    DemoSample("aluminum_can", "Aluminum Can", "Recyclable", 0.94, 15, 3, True, 60,
               "aluminum can", ("can", "aluminum", "aluminium")),
    DemoSample("glass_bottle", "Glass Bottle", "Recyclable", 0.92, 320, 2, True, 90,
               "glass bottle", ("glass", "bottle")),
    DemoSample("paper_sheets", "Paper Sheets", "Recyclable", 0.78, 5, 7, True, 40,
               "paper sheets", ("paper",)),
    DemoSample("milk_carton", "Milk Carton (Tetra Pak)", "Recyclable", 0.89, 22, 10, True, 55,
               "milk carton", ("carton", "milk", "tetra")),
    DemoSample("plastic_container", "Plastic Food Container", "Recyclable", 0.88, 18, 11, True, 65,
               "plastic container", ("plastic", "container")),
)


@dataclass(frozen=True)
class CatalogEntry:
    """A demo sample plus the local state of its image file."""

    sample: DemoSample
    image_path: Path
    image_available: bool
    source_url: str
    attribution: str
    license_name: str


def load_manifest() -> dict[str, dict]:
    """Return manifest entries keyed by sample_id, or {} if no manifest exists."""
    if not MANIFEST_PATH.is_file():
        return {}
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {entry["sample_id"]: entry for entry in data.get("samples", [])}


def load_catalog() -> list[CatalogEntry]:
    """Combine predefined demo data with the image files and manifest metadata."""
    manifest = load_manifest()
    entries: list[CatalogEntry] = []
    for sample in SAMPLES:
        meta = manifest.get(sample.sample_id, {})
        path = SAMPLES_DIR / sample.filename
        entries.append(
            CatalogEntry(
                sample=sample,
                image_path=path,
                image_available=path.is_file(),
                source_url=meta.get("source_url", ""),
                attribution=meta.get("attribution", ""),
                license_name=meta.get("license", ""),
            )
        )
    return entries
