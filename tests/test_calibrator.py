from app.services.calibrator import (
    generate_recommendation,
    adjust_sensitivity_on_feedback,
    MAX_SAFETY_TEMP_CELSIUS,
)
from app.schemas.therapy import VibrationModeEnum, FeedbackTagEnum


def test_calibrator_zero_severity():
    rec = generate_recommendation(cramp_severity=0, sensitivity_index=1.0)
    assert rec.target_temp_celsius == 0.0
    assert rec.vibration_mode == VibrationModeEnum.off
    assert rec.vibration_intensity == 0
    assert rec.duration_minutes == 0


def test_calibrator_mild_severity():
    rec = generate_recommendation(cramp_severity=3, sensitivity_index=1.0)
    assert rec.target_temp_celsius == 37.0
    assert rec.vibration_mode == VibrationModeEnum.pulse
    assert rec.vibration_intensity == 40
    assert rec.duration_minutes == 20


def test_calibrator_moderate_severity():
    rec = generate_recommendation(cramp_severity=6, sensitivity_index=1.0)
    assert rec.target_temp_celsius == 39.5
    assert rec.vibration_mode == VibrationModeEnum.wave
    assert rec.vibration_intensity == 70
    assert rec.duration_minutes == 25


def test_calibrator_severe_severity():
    rec = generate_recommendation(cramp_severity=9, sensitivity_index=1.0)
    assert rec.target_temp_celsius == 42.0
    assert rec.vibration_mode == VibrationModeEnum.wave
    assert rec.vibration_intensity == 90
    assert rec.duration_minutes == 30


def test_calibrator_safety_clamp_high_sensitivity():
    # 42.0 * 1.20 = 50.4, but clamped to 44.0 max
    rec = generate_recommendation(cramp_severity=10, sensitivity_index=1.2)
    assert rec.target_temp_celsius <= MAX_SAFETY_TEMP_CELSIUS
    assert rec.target_temp_celsius == 44.0


def test_adjust_sensitivity_feedback():
    # Insufficient relief -> +0.05
    new_sens, _ = adjust_sensitivity_on_feedback(1.0, FeedbackTagEnum.insufficient_relief)
    assert new_sens == 1.05

    # Too hot -> -0.08
    new_sens2, _ = adjust_sensitivity_on_feedback(1.0, FeedbackTagEnum.too_hot)
    assert new_sens2 == 0.92

    # Insufficient relief at ceiling 1.20
    new_sens_max, _ = adjust_sensitivity_on_feedback(1.18, FeedbackTagEnum.insufficient_relief)
    assert new_sens_max == 1.20

    # Too hot at floor 0.80
    new_sens_min, _ = adjust_sensitivity_on_feedback(0.83, FeedbackTagEnum.too_hot)
    assert new_sens_min == 0.80
