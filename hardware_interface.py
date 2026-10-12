"""Virtual hardware layer. Pure logic, no hardware I/O.

Converts a Decision into the state of simulated conveyor, servo, LCD, and buzzer,
plus an ordered sequence of steps. Nothing here drives physical hardware.

Future integration: a backend that sends serial commands to an Arduino (motor,
servo, LCD, buzzer) can consume the same HardwareState without changes to the decision engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from decision_engine import (
    STATUS_AWAITING,
    STATUS_COMPLETE,
    STATUS_NO_WASTE,
    STATUS_NOT_CONFIRMED,
    STATUS_REVIEW,
    Decision,
)

SERVO_IDLE_DEG = 90
SERVO_ANGLE_FOR_BIN: dict[str, int] = {"Wet Waste Bin": 45, "Dry Waste Bin": 135}

STEP_NAMES: tuple[str, ...] = (
    "Waste detection",
    "Image classification result",
    "Sensor verification",
    "Decision and bin selection",
    "Virtual conveyor activation",
    "Virtual servo movement",
    "Sorting completion or review",
)

# Step states: pending | done | held | blocked | skipped
STEP_STATES_REACHED = ("done", "held", "blocked")


@dataclass(frozen=True)
class SequenceStep:
    number: int
    name: str
    state: str
    detail: str
    lcd_message: Optional[str] = None


@dataclass(frozen=True)
class HardwareState:
    conveyor_running: bool
    conveyor_note: str
    servo_angle: int
    servo_note: str
    selected_bin: Optional[str]
    lcd_lines: tuple[str, str]
    buzzer_on: bool
    system_status: str
    steps: tuple[SequenceStep, ...]
    progress: float  # fraction of steps reached (0.0-1.0)


def _pending_steps() -> tuple[SequenceStep, ...]:
    return tuple(
        SequenceStep(i + 1, name, "pending", "Not started") for i, name in enumerate(STEP_NAMES)
    )


def idle_state() -> HardwareState:
    """Hardware state before any simulation has been run."""
    return HardwareState(
        conveyor_running=False,
        conveyor_note="Stopped (idle)",
        servo_angle=SERVO_IDLE_DEG,
        servo_note="Idle",
        selected_bin=None,
        lcd_lines=("Waste Sorter", "Ready"),
        buzzer_on=False,
        system_status="Idle",
        steps=_pending_steps(),
        progress=0.0,
    )


def simulate(decision: Optional[Decision]) -> HardwareState:
    """Derive the virtual hardware state and step sequence from a decision."""
    if decision is None or decision.status == STATUS_AWAITING:
        return idle_state()

    # IR OFF: the sequence stops at step 1.
    if decision.status == STATUS_NO_WASTE:
        steps = [
            SequenceStep(1, STEP_NAMES[0], "blocked", "IR reports no object; sequence stops",
                         "No Waste Detected"),
        ]
        for i in range(1, 6):
            steps.append(SequenceStep(i + 1, STEP_NAMES[i], "skipped",
                                      "Not started: no waste detected"))
        steps.append(SequenceStep(7, STEP_NAMES[6], "blocked", "No Waste Detected",
                                  "No Waste Detected"))
        return HardwareState(
            conveyor_running=False,
            conveyor_note="Stopped: no waste on belt",
            servo_angle=SERVO_IDLE_DEG,
            servo_note="Idle at 90°: nothing to divert",
            selected_bin=None,
            lcd_lines=decision.lcd_lines,
            buzzer_on=False,
            system_status=decision.label,
            steps=tuple(steps),
            progress=1 / len(STEP_NAMES),
        )

    passed = sum(1 for c in decision.sensor_checks if c.passed)
    total = len(decision.sensor_checks)
    class_line = f"{decision.demo_class} Waste"
    bin_name = decision.proposed_bin or ""

    # Conveyor: running is commanded when waste is detected, but stops for review.
    if decision.status == STATUS_REVIEW:
        conveyor_running = False
        conveyor_note = "Stopped: item held for review"
        conveyor_step = ("held", "Conveyor stopped; item held at the sorting point")
    elif decision.status == STATUS_NOT_CONFIRMED:
        conveyor_running = True
        conveyor_note = "Running command sent; no movement confirmed"
        conveyor_step = ("blocked", "Running command sent, but the encoder shows no movement")
    else:
        conveyor_running = True
        conveyor_note = "Running (simulated)"
        conveyor_step = ("done", f"Running; {decision.sensor_checks[-1].message}")

    # Servo: diverts only when the sorting result is confirmed.
    if decision.status == STATUS_COMPLETE:
        servo_angle = SERVO_ANGLE_FOR_BIN[bin_name]
        servo_note = f"Moved to {servo_angle}° ({bin_name})"
        servo_step = ("done", f"Diverted to the {bin_name} at {servo_angle}°")
    else:
        servo_angle = SERVO_IDLE_DEG
        servo_note = "Holding at 90°: no divert"
        servo_step = ("skipped", "No divert: transport or review gate not cleared")

    if decision.status == STATUS_COMPLETE:
        final_step = ("done", "Sorting Complete (simulated)", "Sorting Complete")
    elif decision.status == STATUS_REVIEW:
        final_step = ("held", "Manual Review Required", "Manual Review Required")
    else:
        final_step = ("blocked", "Transport Not Confirmed", "Check Conveyor")

    steps = (
        SequenceStep(1, STEP_NAMES[0], "done", "IR reports an object", "Waste Detected"),
        SequenceStep(2, STEP_NAMES[1], "done",
                     f"Demo classification: {decision.demo_class} "
                     f"({decision.demo_confidence:.0%} demo confidence)",
                     "Analyzing Sample"),
        SequenceStep(3, STEP_NAMES[2],
                     "done" if passed == total else "held",
                     f"{passed} of {total} checks passed",
                     None),
        SequenceStep(4, STEP_NAMES[3],
                     "done" if decision.status != STATUS_REVIEW else "held",
                     f"Proposed destination: {bin_name}",
                     class_line),
        SequenceStep(5, STEP_NAMES[4], conveyor_step[0], conveyor_step[1], None),
        SequenceStep(6, STEP_NAMES[5], servo_step[0], servo_step[1], None),
        SequenceStep(7, STEP_NAMES[6], final_step[0], final_step[1], final_step[2]),
    )

    reached = sum(1 for s in steps if s.state in STEP_STATES_REACHED)

    return HardwareState(
        conveyor_running=conveyor_running,
        conveyor_note=conveyor_note,
        servo_angle=servo_angle,
        servo_note=servo_note,
        selected_bin=bin_name,
        lcd_lines=decision.lcd_lines,
        buzzer_on=decision.buzzer_on,
        system_status=decision.label,
        steps=steps,
        progress=reached / len(STEP_NAMES),
    )
