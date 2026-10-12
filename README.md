# Hybrid Vision + Multi-Sensor Waste Segregation: Simulator

A Streamlit prototype for the college project *"A Hybrid Computer Vision and Multi-Sensor
Approach for Autonomous Landfill Waste Segregation."*

**This is a simulation.** Classifications are predefined demo data, not model predictions.
Sensor values are fixed or manually overridden, and all hardware (conveyor, servo, LCD, buzzer)
is virtual. Nothing drives physical hardware, and there is no serial or camera integration yet.

## Quick start on Fedora

```bash
cd waste_segregation_sim
python3 -m venv .venv                 # 1. create a virtual environment
source .venv/bin/activate             # 2. activate it
pip install -r requirements.txt       # 3. install dependencies
python scripts/fetch_sample_images.py # 4. download the 16 sample images (needs internet)
streamlit run app.py                  # 5. launch the dashboard
```

Streamlit opens at http://localhost:8501. The app runs even if step 4 fails: missing samples
show a labelled "NOT DOWNLOADED" placeholder and still simulate with their predefined data.

Run the tests (no Streamlit needed):

```bash
python -m unittest discover -s tests -v
```

## Sample images

`scripts/fetch_sample_images.py` searches the Wikimedia Commons API (official API only, no scraping)
for 16 items: 8 Organic and 8 Recyclable. It accepts only CC0, Public domain, CC BY, and CC BY-SA
files, checks that the file title matches the expected item, and validates every download with
Pillow. It writes `assets/samples/manifest.json` with source URL, licence, attribution, and status
for each image.

Options: `--force` re-downloads everything. `--manifest-only` rebuilds the manifest from files on disk
without using the network.

Failures are reported by name. Nothing is substituted silently. To fix a missing image manually, place
a permitted-licence JPEG named `<sample_id>.jpg` in `assets/samples/` and record its source and
licence in the manifest. Review the gallery visually, because the title check is only a heuristic.

## Project layout

| File | Purpose |
|---|---|
| `app.py` | Streamlit dashboard (UI only) |
| `decision_engine.py` | Transparent rule-based decision logic, no UI code |
| `sample_data.py` | Predefined demo data for the 16 samples (single source of truth) |
| `sensor_simulator.py` | Fixed readings, manual overrides, and the `SensorSource` interface |
| `hardware_interface.py` | Virtual conveyor, servo, LCD, buzzer, and the 7-step sequence |
| `scripts/fetch_sample_images.py` | Image download, validation, and manifest generation |
| `assets/samples/` | Downloaded images and `manifest.json` |
| `tests/test_core.py` | Unit tests for the non-UI logic |

## The decision rules

Demo mapping: **Organic → Wet Waste Bin**, **Recyclable → Dry Waste Bin**.

1. No sample selected → request a selection.
2. IR OFF → "No Waste Detected". The conveyor does not run, and nothing is sorted.
3. Sensor verification: moisture must be at least 40% for Organic and at most 30% for Recyclable.
   Weight must be above 0 g. Any failure is a conflict and sends the item to manual review.
4. Demo confidence below the configurable threshold (default 80%) → manual review.
5. Encoder reports 0 pulses → "Transport Not Confirmed". Transport is not declared complete.
6. Otherwise → "Sorting Complete", and the item is diverted to the mapped bin.

Moisture and weight are plausibility checks only. They cannot reliably identify a material on their own.
These rules are predefined and are **not** experimentally validated sensor fusion.

## Upgrade path

| Now (simulation) | Later (hardware / model) | Where to change |
|---|---|---|
| Predefined `demo_class` and `demo_confidence` | Trained image classifier output | `sample_data.py`, replace with a classifier that returns the same fields |
| Sample image library | ESP32-CAM frames | `load_catalog()` in `sample_data.py` |
| Fixed sensor readings | Arduino UNO over USB serial | New class implementing `SensorSource.read()` in `sensor_simulator.py` |
| Virtual motor, servo, LCD, buzzer | Actual actuator commands | New backend that consumes `HardwareState` in `hardware_interface.py` |

No serial, camera, or model dependencies are installed or imported today.

## Known limitations

- The demo classifications are fixed values. No model has been trained, and none is used.
- Uploaded images are previewed only. The app does not classify them.
- The servo and conveyor states are derived from rules. Nothing is moved.
- Layout was verified with a stubbed Streamlit build. Pixel-level styling should be checked in a browser.
