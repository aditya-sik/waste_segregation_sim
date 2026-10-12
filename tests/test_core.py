"""Tests for the non-UI logic. Run with:  python -m unittest discover -s tests -v

These tests do not import Streamlit, so they run without the UI dependencies.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decision_engine import (  # noqa: E402
    CLASS_TO_BIN,
    STATUS_AWAITING,
    STATUS_COMPLETE,
    STATUS_NO_WASTE,
    STATUS_NOT_CONFIRMED,
    STATUS_REVIEW,
    DecisionConfig,
    evaluate,
)
from hardware_interface import SERVO_IDLE_DEG, STEP_NAMES, simulate  # noqa: E402
from sample_data import SAMPLES  # noqa: E402
from sensor_simulator import SimulatedSensors, apply_overrides, readings_for_sample  # noqa: E402


def sample_by_id(sample_id):
    return next(s for s in SAMPLES if s.sample_id == sample_id)


class SampleDataTests(unittest.TestCase):
    def test_sixteen_samples_eight_per_class(self):
        self.assertEqual(len(SAMPLES), 16)
        classes = [s.demo_class for s in SAMPLES]
        self.assertEqual(classes.count("Organic"), 8)
        self.assertEqual(classes.count("Recyclable"), 8)

    def test_ids_and_filenames_are_unique(self):
        self.assertEqual(len({s.sample_id for s in SAMPLES}), 16)
        self.assertEqual(len({s.filename for s in SAMPLES}), 16)

    def test_values_are_in_valid_ranges_and_classes_are_mapped(self):
        for s in SAMPLES:
            with self.subTest(sample=s.sample_id):
                self.assertIn(s.demo_class, CLASS_TO_BIN)
                self.assertTrue(0.0 < s.demo_confidence <= 1.0)
                self.assertTrue(0.0 <= s.moisture_pct <= 100.0)
                self.assertGreaterEqual(s.weight_g, 0)
                self.assertGreaterEqual(s.encoder_pulses, 0)

    def test_demo_values_match_the_brief(self):
        banana = sample_by_id("banana_peel")
        self.assertEqual((banana.demo_class, banana.demo_confidence, banana.weight_g,
                          banana.moisture_pct, banana.encoder_pulses),
                         ("Organic", 0.94, 125, 82, 120))
        bottle = sample_by_id("plastic_bottle")
        self.assertEqual((bottle.demo_class, bottle.demo_confidence, bottle.weight_g,
                          bottle.moisture_pct, bottle.encoder_pulses),
                         ("Recyclable", 0.91, 28, 12, 95))

    def test_repeated_reads_are_deterministic(self):
        s = sample_by_id("banana_peel")
        self.assertEqual(readings_for_sample(s), readings_for_sample(s))
        self.assertEqual(evaluate(s, readings_for_sample(s)), evaluate(s, readings_for_sample(s)))


class DecisionEngineTests(unittest.TestCase):
    def test_no_sample_requests_selection(self):
        d = evaluate(None, None)
        self.assertEqual(d.status, STATUS_AWAITING)
        self.assertFalse(d.sorting_triggered)

    def test_organic_default_routes_to_wet_bin(self):
        s = sample_by_id("banana_peel")
        d = evaluate(s, readings_for_sample(s))
        self.assertEqual(d.status, STATUS_COMPLETE)
        self.assertEqual(d.proposed_bin, "Wet Waste Bin")
        self.assertTrue(d.sorting_triggered)
        self.assertTrue(d.conveyor_moving)

    def test_recyclable_default_routes_to_dry_bin(self):
        s = sample_by_id("plastic_bottle")
        d = evaluate(s, readings_for_sample(s))
        self.assertEqual(d.status, STATUS_COMPLETE)
        self.assertEqual(d.proposed_bin, "Dry Waste Bin")

    def test_ir_off_prevents_sorting(self):
        s = sample_by_id("banana_peel")
        r = apply_overrides(readings_for_sample(s), ir_detected=False)
        d = evaluate(s, r)
        self.assertEqual(d.status, STATUS_NO_WASTE)
        self.assertFalse(d.sorting_triggered)
        self.assertIsNone(d.proposed_bin)
        hw = simulate(d)
        self.assertFalse(hw.conveyor_running)
        self.assertEqual(hw.servo_angle, SERVO_IDLE_DEG)
        self.assertEqual(hw.steps[0].state, "blocked")

    def test_low_confidence_triggers_review(self):
        s = sample_by_id("paper_sheets")  # predefined confidence 0.78, below 0.80
        d = evaluate(s, readings_for_sample(s), DecisionConfig(confidence_threshold=0.80))
        self.assertEqual(d.status, STATUS_REVIEW)
        self.assertFalse(d.sorting_triggered)
        self.assertTrue(any("below" in reason for reason in d.review_reasons))

    def test_threshold_is_configurable(self):
        s = sample_by_id("paper_sheets")
        d = evaluate(s, readings_for_sample(s), DecisionConfig(confidence_threshold=0.70))
        self.assertEqual(d.status, STATUS_COMPLETE)

    def test_missing_encoder_pulses_do_not_declare_transport_complete(self):
        s = sample_by_id("plastic_bottle")
        r = apply_overrides(readings_for_sample(s), encoder_pulses=0)
        d = evaluate(s, r)
        self.assertEqual(d.status, STATUS_NOT_CONFIRMED)
        self.assertFalse(d.sorting_triggered)
        hw = simulate(d)
        self.assertEqual(hw.servo_angle, SERVO_IDLE_DEG)
        self.assertEqual(hw.steps[4].state, "blocked")
        self.assertEqual(hw.steps[6].state, "blocked")

    def test_moisture_override_creates_conflict_and_review(self):
        s = sample_by_id("plastic_bottle")  # Recyclable, moisture 12%
        r = apply_overrides(readings_for_sample(s), moisture_pct=80)
        d = evaluate(s, r)
        self.assertEqual(d.status, STATUS_REVIEW)
        self.assertTrue(any("Moisture" in c for c in d.conflicts))
        failed = [c for c in d.sensor_checks if not c.passed]
        self.assertEqual([c.name for c in failed], ["Moisture"])

    def test_zero_weight_with_ir_is_a_conflict(self):
        s = sample_by_id("banana_peel")
        r = apply_overrides(readings_for_sample(s), weight_g=0)
        d = evaluate(s, r)
        self.assertEqual(d.status, STATUS_REVIEW)
        self.assertTrue(any("weight" in c.lower() for c in d.conflicts))

    def test_overrides_change_the_outcome_both_ways(self):
        s = sample_by_id("banana_peel")
        base = readings_for_sample(s)
        self.assertEqual(evaluate(s, base).status, STATUS_COMPLETE)
        self.assertEqual(evaluate(s, apply_overrides(base, moisture_pct=5)).status, STATUS_REVIEW)

    def test_stages_are_reported_separately(self):
        s = sample_by_id("banana_peel")
        d = evaluate(s, readings_for_sample(s))
        self.assertEqual(d.demo_class, "Organic")
        self.assertEqual(d.proposed_bin, "Wet Waste Bin")
        self.assertEqual(d.label, "Sorting Complete")
        self.assertTrue(d.explanation)

    def test_explanation_states_predefined_rule(self):
        s = sample_by_id("banana_peel")
        d = evaluate(s, readings_for_sample(s))
        text = " ".join(d.explanation).lower()
        self.assertIn("demo rule", text)
        self.assertIn("plausibility", text)


class SensorTests(unittest.TestCase):
    def test_overrides_are_clamped(self):
        s = sample_by_id("banana_peel")
        base = readings_for_sample(s)
        r = apply_overrides(base, moisture_pct=250, weight_g=-5, encoder_pulses=-3)
        self.assertEqual(r.moisture_pct, 100.0)
        self.assertEqual(r.weight_g, 0.0)
        self.assertEqual(r.encoder_pulses, 0)

    def test_simulated_sensor_source(self):
        s = sample_by_id("aluminum_can")
        src = SimulatedSensors(s, overrides={"ir_detected": False})
        self.assertFalse(src.read().ir_detected)
        self.assertEqual(SimulatedSensors(s).read(), readings_for_sample(s))


class HardwareTests(unittest.TestCase):
    def test_idle_state_before_run(self):
        hw = simulate(None)
        self.assertFalse(hw.conveyor_running)
        self.assertEqual(hw.progress, 0.0)
        self.assertEqual([st.name for st in hw.steps], list(STEP_NAMES))

    def test_complete_sorting_moves_servo_to_bin(self):
        s = sample_by_id("banana_peel")
        hw = simulate(evaluate(s, readings_for_sample(s)))
        self.assertEqual(hw.servo_angle, 45)
        self.assertEqual(hw.selected_bin, "Wet Waste Bin")
        self.assertEqual(hw.lcd_lines, ("Organic Waste", "Sorting Complete"))
        self.assertFalse(hw.buzzer_on)
        self.assertEqual(hw.progress, 1.0)

    def test_recyclable_servo_goes_to_dry_bin(self):
        s = sample_by_id("cardboard_box")
        hw = simulate(evaluate(s, readings_for_sample(s)))
        self.assertEqual(hw.servo_angle, 135)

    def test_review_holds_item_and_sounds_buzzer(self):
        s = sample_by_id("paper_sheets")
        hw = simulate(evaluate(s, readings_for_sample(s)))
        self.assertFalse(hw.conveyor_running)
        self.assertEqual(hw.servo_angle, SERVO_IDLE_DEG)
        self.assertTrue(hw.buzzer_on)
        self.assertEqual(hw.lcd_lines[1], "Manual Review Required")

    def test_sequence_has_seven_ordered_steps(self):
        s = sample_by_id("banana_peel")
        hw = simulate(evaluate(s, readings_for_sample(s)))
        self.assertEqual(len(hw.steps), 7)
        self.assertEqual([st.name for st in hw.steps], list(STEP_NAMES))


class CatalogTests(unittest.TestCase):
    def test_catalog_loads_without_manifest_or_images(self):
        from sample_data import load_catalog
        catalog = load_catalog()
        self.assertEqual(len(catalog), 16)
        for entry in catalog:
            self.assertIsNotNone(entry.image_path)


if __name__ == "__main__":
    unittest.main()
