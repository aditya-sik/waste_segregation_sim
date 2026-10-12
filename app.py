"""Streamlit dashboard: Hybrid Computer Vision + Multi-Sensor Waste Segregation.

SIMULATION ONLY. Classifications are predefined demo data, sensor values are
fixed or manually overridden, and all hardware outputs are virtual.

Run with:  streamlit run app.py
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import streamlit as st
from PIL import Image, ImageDraw

from decision_engine import (
    CLASS_TO_BIN,
    STATUS_COMPLETE,
    STATUS_NO_WASTE,
    STATUS_NOT_CONFIRMED,
    STATUS_REVIEW,
    Decision,
    DecisionConfig,
    evaluate,
)
from hardware_interface import SERVO_ANGLE_FOR_BIN, simulate
from sample_data import CatalogEntry, load_catalog
from sensor_simulator import SensorReadings, apply_overrides, readings_for_sample

THUMB_SIZE = (220, 165)
PREVIEW_SIZE = (520, 390)
GALLERY_COLUMNS = 4

st.set_page_config(
    page_title="Waste Segregation Simulator",
    page_icon="♻️",
    layout="wide",
)

st.markdown(
    """
    <style>
      .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
      .sim-badge {
        display: inline-block; padding: 0.2rem 0.7rem; border-radius: 999px;
        background: #fff4d6; color: #7a5200; border: 1px solid #f0c75e;
        font-weight: 600; font-size: 0.8rem; letter-spacing: 0.04em;
      }
      div[data-testid="stMetricValue"] { font-size: 1.35rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _placeholder(size: tuple[int, int], label: str) -> Image.Image:
    """A neutral grey card that clearly states the image is missing (not a sample photo)."""
    img = Image.new("RGB", size, (232, 232, 232))
    draw = ImageDraw.Draw(img)
    left, top, right, bottom = draw.textbbox((0, 0), label)
    w, h = right - left, bottom - top
    draw.text(((size[0] - w) / 2, (size[1] - h) / 2), label, fill=(95, 95, 95))
    return img


@st.cache_data(show_spinner=False)
def render_image(path_str: str, max_size: tuple[int, int]) -> bytes:
    """Load a sample image as PNG bytes scaled to fit max_size, or a labelled placeholder."""
    path = Path(path_str)
    img: Image.Image
    if path.is_file():
        try:
            img = Image.open(path).convert("RGB")
        except OSError:
            img = _placeholder(max_size, "FILE UNREADABLE")
    else:
        img = _placeholder(max_size, "NOT DOWNLOADED")
    img.thumbnail(max_size)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _select_sample(sample_id: str) -> None:
    st.session_state.selected_id = sample_id
    st.session_state.run_active = False


def _reset_simulation() -> None:
    st.session_state.selected_id = None
    st.session_state.run_active = False
    st.session_state.history = []
    st.session_state.overrides_on = False
    for key in [k for k in st.session_state.keys() if k.startswith("ov_")]:
        del st.session_state[key]


def _status_box(decision: Decision) -> None:
    text = decision.label
    if decision.status == STATUS_COMPLETE:
        st.success(f"**{text}** (simulated): proposed destination {decision.proposed_bin}")
    elif decision.status == STATUS_REVIEW:
        st.warning(f"**{text}**: item held, not sorted automatically")
    elif decision.status == STATUS_NOT_CONFIRMED:
        st.error(f"**{text}**: encoder shows no movement, so transport is not declared complete")
    else:
        st.info(f"**{text}**: sorting not triggered")


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
st.session_state.setdefault("selected_id", None)
st.session_state.setdefault("run_active", False)
st.session_state.setdefault("history", [])
st.session_state.setdefault("overrides_on", False)

catalog = load_catalog()
by_id: dict[str, CatalogEntry] = {e.sample.sample_id: e for e in catalog}
entry = by_id.get(st.session_state.selected_id)
sample = entry.sample if entry else None

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Settings")
    threshold = st.slider(
        "Demo confidence review threshold",
        min_value=0.50,
        max_value=0.99,
        value=0.80,
        step=0.01,
        format="%.2f",
        help="Samples whose demo confidence falls below this value are flagged for manual review.",
    )
    st.caption("Image library: "
               f"{sum(e.image_available for e in catalog)} of {len(catalog)} sample images present.")
    if not all(e.image_available for e in catalog):
        st.warning("Some images are missing. Run `python scripts/fetch_sample_images.py` "
                   "while online. Missing samples still simulate with their predefined data.")
    st.divider()
    st.markdown(
        "**Mode:** simulation only\n\n"
        "**Classification:** predefined demo data\n\n"
        "**Hardware:** virtual, nothing is driven"
    )

config = DecisionConfig(confidence_threshold=threshold)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("Hybrid Vision + Multi-Sensor Waste Segregation")
st.markdown(
    "Autonomous landfill waste segregation, college project prototype. "
    "A rule-based decision engine combines a demo classification with IR, weight, moisture, "
    "and encoder readings to choose between a Wet and a Dry waste bin."
)
st.markdown('<span class="sim-badge">SIMULATION MODE</span>', unsafe_allow_html=True)
st.info(
    "This version uses **predefined demonstration data**. Demo classifications are not real AI "
    "predictions, sensor values are fixed or manually overridden, and all hardware outputs are virtual."
)

# ---------------------------------------------------------------------------
# Sample gallery
# ---------------------------------------------------------------------------
st.subheader("1. Sample image gallery")
st.caption("Select a sample to load its predefined demo data.")

# Hide the last four sample cards from the gallery UI.
display_catalog = catalog[:-4] if len(catalog) > 4 else []
for start in range(0, len(display_catalog), GALLERY_COLUMNS):
    row = display_catalog[start:start + GALLERY_COLUMNS]
    cols = st.columns(GALLERY_COLUMNS)
    for col, item in zip(cols, row):
        sid = item.sample.sample_id
        is_selected = sid == st.session_state.selected_id
        with col:
            st.image(render_image(str(item.image_path), THUMB_SIZE))
            st.markdown(f"**{item.sample.display_name}**")
            cls_colour = "green" if item.sample.demo_class == "Organic" else "blue"
            st.markdown(f":{cls_colour}[{item.sample.demo_class}]"
                        + ("" if item.image_available else " · ⚠ image missing"))
            st.button(
                "Selected ✓" if is_selected else "Select",
                key=f"select_{sid}",
                on_click=_select_sample,
                args=(sid,),
                type="primary" if is_selected else "secondary",
            )

with st.expander("Optional: preview your own image (no classification)"):
    uploaded = st.file_uploader("Upload a JPG, PNG or WebP image", type=["jpg", "jpeg", "png", "webp"])
    if uploaded is not None:
        try:
            upload_img = Image.open(uploaded).convert("RGB")
            upload_img.thumbnail(PREVIEW_SIZE)
            st.image(upload_img, caption=f"Uploaded: {uploaded.name}")
            st.warning(
                "Automated classification is unavailable: this prototype has no trained model, so no "
                "AI prediction is shown for uploaded images. Use the sample gallery to run the simulation."
            )
        except OSError:
            st.error("This file could not be read as an image.")

# ---------------------------------------------------------------------------
# Selected sample: preview, classification, sensors
# ---------------------------------------------------------------------------
st.subheader("2. Selected sample")
left, right = st.columns([1.05, 1])

with left:
    if sample is None:
        st.info("Select a sample image above to load its predefined demo data.")
    else:
        st.image(render_image(str(entry.image_path), PREVIEW_SIZE), caption=sample.display_name)
        if entry.image_available:
            st.caption(f"Attribution: {entry.attribution or 'not recorded'}  ·  "
                       f"Source: {entry.source_url or 'not recorded'}")
        else:
            st.warning("Image not downloaded. The simulation still runs on the predefined data.")

    run_clicked = st.button(
        "▶ Run Simulation",
        type="primary",
        disabled=sample is None,
        
        key="run_button",
    )
    st.button("↺ Reset Simulation", on_click=_reset_simulation,
              key="reset_button")

with right:
    st.markdown("#### Classification panel")
    if sample is None:
        st.caption("No sample selected.")
    else:
        st.caption("Predefined demo data. This is **not** a measured model prediction.")
        c1, c2 = st.columns(2)
        c1.metric("Demo Classification", sample.demo_class)
        c2.metric("Demo Confidence", f"{sample.demo_confidence:.0%}")
        st.progress(sample.demo_confidence)
        st.metric("Proposed Waste Bin", CLASS_TO_BIN[sample.demo_class])

    st.markdown("#### Sensor panel")
    readings: SensorReadings | None = None
    if sample is None:
        st.caption("Sensor readings appear after a sample is selected.")
    else:
        base = readings_for_sample(sample)
        st.checkbox("Enable manual sensor overrides", key="overrides_on",
                    help="Adjust the readings to see how the decision changes.")
        if st.session_state.overrides_on:
            sid = sample.sample_id
            o1, o2 = st.columns(2)
            ir_val = o1.checkbox("IR detected", value=base.ir_detected, key=f"ov_ir_{sid}")
            weight_val = o2.number_input("Weight (g)", min_value=0.0, max_value=5000.0,
                                         value=float(base.weight_g), step=1.0, key=f"ov_w_{sid}")
            moisture_val = o1.slider("Moisture (%)", 0.0, 100.0, float(base.moisture_pct),
                                     step=1.0, key=f"ov_m_{sid}")
            pulses_val = o2.number_input("Encoder pulses", min_value=0, max_value=1000,
                                         value=int(base.encoder_pulses), step=1, key=f"ov_p_{sid}")
            readings = apply_overrides(base, ir_detected=ir_val, weight_g=weight_val,
                                       moisture_pct=moisture_val, encoder_pulses=pulses_val)
            st.caption("Manual overrides are active. The decision uses these values.")
        else:
            readings = base

        s1, s2 = st.columns(2)
        s1.metric("IR sensor", "Detected" if readings.ir_detected else "Not detected")
        s2.metric("Weight (HX711)", f"{readings.weight_g:.0f} g")
        s3, s4 = st.columns(2)
        s3.metric("Soil moisture", f"{readings.moisture_pct:.0f} %")
        s4.metric("Encoder pulses", f"{readings.encoder_pulses}",
                  help="Pulse count from the optical rotary encoder")
        st.caption("Conveyor movement: " + ("moving (pulses present)" if readings.encoder_pulses > 0
                                            else "no movement signal"))

# ---------------------------------------------------------------------------
# Run handling: record history, then evaluate with the current readings
# ---------------------------------------------------------------------------
if run_clicked and sample is not None and readings is not None:
    st.session_state.run_active = True
    run_decision = evaluate(sample, readings, config)
    st.session_state.history.insert(0, {
        "#": len(st.session_state.history) + 1,
        "Processed image": sample.display_name,
        "Demo class": sample.demo_class,
        "Demo confidence": f"{sample.demo_confidence:.0%}",
        "Weight (g)": f"{readings.weight_g:.0f}",
        "Moisture (%)": f"{readings.moisture_pct:.0f}",
        "Proposed bin": run_decision.proposed_bin or "None",
        "Final status": run_decision.label,
        "Overrides": "Yes" if st.session_state.overrides_on else "No",
    })

run_active = st.session_state.run_active and sample is not None and readings is not None
decision: Decision | None = evaluate(sample, readings, config) if run_active else None

# ---------------------------------------------------------------------------
# Decision panel
# ---------------------------------------------------------------------------
st.subheader("3. Decision panel")
if sample is None:
    st.info("Select a sample image to begin.")
elif decision is None:
    st.info("Press **Run Simulation** to process the selected sample with the current sensor readings.")
elif decision.status == STATUS_NO_WASTE:
    st.info("**No Waste Detected.** The IR sensor reports no object, so sorting is not triggered.")
    st.markdown("**Why:**")
    for line in decision.explanation:
        st.markdown(f"- {line}")
else:
    d1, d2 = st.columns([1, 1])
    with d1:
        st.markdown("**Sensor verification**")
        for check in decision.sensor_checks:
            text = f"**{check.name}:** {check.message}"
            (st.success if check.passed else st.warning)(text)
        if decision.conflicts:
            st.markdown("**Disagreement detected**")
            for conflict in decision.conflicts:
                st.error(conflict)
        if decision.review_reasons:
            st.markdown("**Review flags**")
            for reason in decision.review_reasons:
                st.warning(reason)
    with d2:
        st.markdown("**Final decision (simulated)**")
        _status_box(decision)
        st.markdown("**Why the system chose this result**")
        for line in decision.explanation:
            st.markdown(f"- {line}")
        st.caption("Demo classification, sensor verification, proposed destination, and final "
                   "status are evaluated separately. Rules are predefined and not experimentally validated.")

# ---------------------------------------------------------------------------
# Virtual hardware panel
# ---------------------------------------------------------------------------
st.subheader("4. Virtual hardware panel")
st.caption("**All hardware here is SIMULATED.** No physical device is being driven.")
hw = simulate(decision)

h1, h2, h3, h4, h5 = st.columns(5)
h1.metric("DC conveyor motor", "Running" if hw.conveyor_running else "Stopped",
          help=hw.conveyor_note)
h2.metric("Servo position", f"{hw.servo_angle}°", help=hw.servo_note)
h3.metric("Selected bin", hw.selected_bin or "None")
h4.metric("Buzzer", "ON" if hw.buzzer_on else "OFF")
h5.metric("System status", hw.system_status)

lcd_col, seq_col = st.columns([1, 1.4])
with lcd_col:
    st.markdown("**Virtual LCD (16×2)**")
    st.code(f"{hw.lcd_lines[0]:<16}\n{hw.lcd_lines[1]:<16}", language=None)

    st.markdown("**Servo angle indicator**")
    angle_text = " · ".join(
        f"**[{angle}°]** {name}" if angle == hw.servo_angle and hw.selected_bin == name
        else f"{angle}° {name}"
        for name, angle in SERVO_ANGLE_FOR_BIN.items()
    )
    st.markdown(f"Idle 90° · {angle_text}")
    st.progress(min(hw.servo_angle / 180, 1.0), text=f"Servo at {hw.servo_angle}° of 180°")

with seq_col:
    st.markdown("**Sequence**")
    st.progress(hw.progress, text=f"{round(hw.progress * len(hw.steps))} of {len(hw.steps)} steps reached")
    icons = {"done": "✅", "held": "⏸️", "blocked": "⛔", "skipped": "➖", "pending": "⬜"}
    for step in hw.steps:
        lcd_note = f" · LCD: *{step.lcd_message}*" if step.lcd_message else ""
        st.markdown(f"{icons[step.state]} **{step.number}. {step.name}**: {step.detail}{lcd_note}")

# ---------------------------------------------------------------------------
# Simulation history
# ---------------------------------------------------------------------------
st.subheader("5. Simulation history")
if st.session_state.history:
    st.dataframe(st.session_state.history, hide_index=True)
else:
    st.caption("No simulations have been run yet.")
