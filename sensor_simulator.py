"""Simulated sensor layer.

Readings come from the predefined sample data, optionally replaced by manual
overrides. This module performs no hardware I/O.

Future integration: a serial-backed class (Arduino UNO) that also provides
read() -> SensorReadings can replace SimulatedSensors without changes to the
decision engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from sample_data import DemoSample

WEIGHT_MAX_G = 5000.0
PULSES_MAX = 1000


@dataclass(frozen=True)
class SensorReadings:
    ir_detected: bool
    weight_g: float
    moisture_pct: float
    encoder_pulses: int


class SensorSource(Protocol):
    """Interface any sensor backend (simulated or hardware) must satisfy."""

    def read(self) -> SensorReadings: ...


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def readings_for_sample(sample: DemoSample) -> SensorReadings:
    """Return the fixed sensor readings configured for a sample."""
    return SensorReadings(
        ir_detected=sample.ir_detected,
        weight_g=float(sample.weight_g),
        moisture_pct=float(sample.moisture_pct),
        encoder_pulses=int(sample.encoder_pulses),
    )


def apply_overrides(
    base: SensorReadings,
    *,
    ir_detected: Optional[bool] = None,
    weight_g: Optional[float] = None,
    moisture_pct: Optional[float] = None,
    encoder_pulses: Optional[int] = None,
) -> SensorReadings:
    """Return new readings with any supplied values replaced and clamped to valid ranges."""
    return SensorReadings(
        ir_detected=base.ir_detected if ir_detected is None else bool(ir_detected),
        weight_g=base.weight_g if weight_g is None else _clamp(float(weight_g), 0.0, WEIGHT_MAX_G),
        moisture_pct=(
            base.moisture_pct if moisture_pct is None else _clamp(float(moisture_pct), 0.0, 100.0)
        ),
        encoder_pulses=(
            base.encoder_pulses
            if encoder_pulses is None
            else int(_clamp(int(encoder_pulses), 0, PULSES_MAX))
        ),
    )


class SimulatedSensors:
    """SensorSource backed by a sample's fixed readings plus optional overrides."""

    def __init__(self, sample: DemoSample, overrides: Optional[dict] = None) -> None:
        self._base = readings_for_sample(sample)
        self._overrides = overrides or {}

    def read(self) -> SensorReadings:
        return apply_overrides(self._base, **self._overrides)
