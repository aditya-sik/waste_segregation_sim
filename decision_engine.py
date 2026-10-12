"""Rule-based decision engine.

The rules here are PREDEFINED DEMONSTRATION RULES, not experimentally
validated sensor fusion. Weight and moisture cannot reliably identify a
material category on their own. In this prototype they act only as
plausibility checks against the predefined demo classification.

This module contains no UI code. A trained classifier can later supply
`demo_class` and `demo_confidence` through DemoSample without changing these rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sample_data import DemoSample
from sensor_simulator import SensorReadings

CLASS_TO_BIN: dict[str, str] = {
    "Organic": "Wet Waste Bin",
    "Recyclable": "Dry Waste Bin",
}

STATUS_AWAITING = "AWAITING_SELECTION"
STATUS_NO_WASTE = "NO_WASTE_DETECTED"
STATUS_REVIEW = "MANUAL_REVIEW_REQUIRED"
STATUS_NOT_CONFIRMED = "TRANSPORT_NOT_CONFIRMED"
STATUS_COMPLETE = "SORTING_COMPLETE"

STATUS_LABELS: dict[str, str] = {
    STATUS_AWAITING: "Awaiting Selection",
    STATUS_NO_WASTE: "No Waste Detected",
    STATUS_REVIEW: "Manual Review Required",
    STATUS_NOT_CONFIRMED: "Transport Not Confirmed",
    STATUS_COMPLETE: "Sorting Complete",
}


@dataclass(frozen=True)
class DecisionConfig:
    confidence_threshold: float = 0.80
    organic_min_moisture_pct: float = 40.0
    recyclable_max_moisture_pct: float = 30.0


@dataclass(frozen=True)
class SensorCheck:
    name: str
    passed: bool
    message: str


@dataclass
class Decision:
    status: str
    demo_class: Optional[str] = None          # predefined classification
    demo_confidence: Optional[float] = None   # predefined confidence
    proposed_bin: Optional[str] = None        # destination from the class mapping
    sensor_checks: list[SensorCheck] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    conveyor_moving: bool = False             # encoder confirms movement
    sorting_triggered: bool = False           # True only when the item is diverted
    explanation: list[str] = field(default_factory=list)
    lcd_lines: tuple[str, str] = ("", "")
    buzzer_on: bool = False

    @property
    def label(self) -> str:
        return STATUS_LABELS[self.status]


def evaluate(
    sample: Optional[DemoSample],
    readings: Optional[SensorReadings],
    config: DecisionConfig = DecisionConfig(),
) -> Decision:
    """Apply the transparent demo rules to a sample and its current sensor readings."""

    # Rule: no sample selected -> request a selection.
    if sample is None or readings is None:
        return Decision(
            status=STATUS_AWAITING,
            lcd_lines=("Waste Sorter", "Select Sample"),
            explanation=[
                "No sample image is selected, so there is no demo classification. "
                "Choose an image from the gallery, then press Run Simulation."
            ],
        )

    proposed_bin = CLASS_TO_BIN[sample.demo_class]
    class_line = f"{sample.demo_class} Waste"

    # Rule: IR OFF -> no waste detected, no sorting.
    if not readings.ir_detected:
        return Decision(
            status=STATUS_NO_WASTE,
            demo_class=sample.demo_class,
            demo_confidence=sample.demo_confidence,
            proposed_bin=None,
            conveyor_moving=False,
            sorting_triggered=False,
            explanation=[
                "The IR sensor reports no object at the sorting point, so the system reports No Waste Detected.",
                "The demo classification is shown for reference only. It is not acted upon, "
                "the conveyor is not started, and the servo does not move.",
            ],
            lcd_lines=("No Waste Detected", "Idle"),
        )

    checks: list[SensorCheck] = []
    conflicts: list[str] = []

    # Plausibility check: moisture against the predefined class.
    if sample.demo_class == "Organic":
        moisture_ok = readings.moisture_pct >= config.organic_min_moisture_pct
        expectation = f"expected at least {config.organic_min_moisture_pct:.0f}% for organic waste"
    else:
        moisture_ok = readings.moisture_pct <= config.recyclable_max_moisture_pct
        expectation = f"expected at most {config.recyclable_max_moisture_pct:.0f}% for dry recyclables"
    checks.append(SensorCheck(
        "Moisture",
        moisture_ok,
        f"{readings.moisture_pct:.0f}% ({expectation})",
    ))
    if not moisture_ok:
        conflicts.append(
            f"Moisture of {readings.moisture_pct:.0f}% conflicts with the "
            f"{sample.demo_class} classification ({expectation})."
        )

    # Plausibility check: an object detected by IR must have measurable weight.
    weight_ok = readings.weight_g > 0
    checks.append(SensorCheck(
        "Weight",
        weight_ok,
        f"Load cell reads {readings.weight_g:.0f} g"
        if weight_ok
        else "Load cell reads 0 g although IR detects an object",
    ))
    if not weight_ok:
        conflicts.append("IR detects an object but the weight sensor reads 0 g.")

    # Transport confirmation: encoder pulses are required before transport can be declared complete.
    conveyor_moving = readings.encoder_pulses > 0
    checks.append(SensorCheck(
        "Conveyor encoder",
        conveyor_moving,
        f"{readings.encoder_pulses} pulses, movement confirmed"
        if conveyor_moving
        else "0 pulses, movement not confirmed",
    ))

    review_reasons: list[str] = []
    if conflicts:
        review_reasons.append("Sensor readings conflict with the demo classification.")
    if sample.demo_confidence < config.confidence_threshold:
        review_reasons.append(
            f"Demo confidence {sample.demo_confidence:.0%} is below the "
            f"{config.confidence_threshold:.0%} review threshold."
        )

    # Final status: review takes priority, then transport confirmation.
    if review_reasons:
        status = STATUS_REVIEW
    elif not conveyor_moving:
        status = STATUS_NOT_CONFIRMED
    else:
        status = STATUS_COMPLETE

    explanation = [
        f"Demo rule: {sample.demo_class} maps to the {proposed_bin}. Moisture and weight are "
        "used only as plausibility checks in this prototype, not to identify the material.",
    ]
    if status == STATUS_REVIEW:
        explanation.append(
            "Held for manual review: " + " ".join(review_reasons)
            + " The servo does not divert the item automatically."
        )
    elif status == STATUS_NOT_CONFIRMED:
        explanation.append(
            "The encoder reports no pulses, so conveyor movement is not confirmed. Transport is "
            "not declared complete and the servo does not divert the item."
        )
    else:
        explanation.append(
            f"All checks passed and movement is confirmed, so the item is diverted to the {proposed_bin}."
        )

    lcd_by_status = {
        STATUS_COMPLETE: (class_line, "Sorting Complete"),
        STATUS_REVIEW: (class_line, "Manual Review Required"),
        STATUS_NOT_CONFIRMED: (class_line, "Check Conveyor"),
    }

    return Decision(
        status=status,
        demo_class=sample.demo_class,
        demo_confidence=sample.demo_confidence,
        proposed_bin=proposed_bin,
        sensor_checks=checks,
        conflicts=conflicts,
        review_reasons=review_reasons,
        conveyor_moving=conveyor_moving,
        sorting_triggered=status == STATUS_COMPLETE,
        explanation=explanation,
        lcd_lines=lcd_by_status[status],
        buzzer_on=status in (STATUS_REVIEW, STATUS_NOT_CONFIRMED),
    )
