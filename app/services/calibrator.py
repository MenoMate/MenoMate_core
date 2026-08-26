from typing import Tuple
from app.schemas.therapy import FeedbackTagEnum, TherapyRecommendationResponse, VibrationModeEnum

# Absolute Hardware Safety Limit
MAX_SAFETY_TEMP_CELSIUS = 44.0
MIN_SAFETY_TEMP_CELSIUS = 35.0

# Sensitivity Boundaries
MIN_SENSITIVITY_INDEX = 0.80
MAX_SENSITIVITY_INDEX = 1.20


def generate_recommendation(
    cramp_severity: int,
    sensitivity_index: float = 1.0,
) -> TherapyRecommendationResponse:
    """
    Deterministic baseline recommendation rule engine for dynamic thermal and vibration control.
    """
    # Clamp sensitivity within valid range
    sens = max(MIN_SENSITIVITY_INDEX, min(MAX_SENSITIVITY_INDEX, sensitivity_index))

    if cramp_severity == 0:
        return TherapyRecommendationResponse(
            cramp_severity=0,
            target_temp_celsius=0.0,
            vibration_mode=VibrationModeEnum.off,
            vibration_intensity=0,
            duration_minutes=0,
            reasoning="No cramp pain reported (severity 0). Thermal and vibration hardware remain idle.",
            applied_sensitivity_index=sens,
        )

    elif 1 <= cramp_severity <= 4:
        raw_temp = 37.0 * sens
        clamped_temp = max(35.0, min(38.0, raw_temp))
        # Ensure strict ceiling
        final_temp = min(clamped_temp, MAX_SAFETY_TEMP_CELSIUS)
        return TherapyRecommendationResponse(
            cramp_severity=cramp_severity,
            target_temp_celsius=round(final_temp, 1),
            vibration_mode=VibrationModeEnum.pulse,
            vibration_intensity=40,
            duration_minutes=20,
            reasoning="Mild cramps (severity 1-4). Applying gentle pulse vibration (40%) and soothing thermal baseline.",
            applied_sensitivity_index=sens,
        )

    elif 5 <= cramp_severity <= 7:
        raw_temp = 39.5 * sens
        clamped_temp = max(38.0, min(41.0, raw_temp))
        final_temp = min(clamped_temp, MAX_SAFETY_TEMP_CELSIUS)
        return TherapyRecommendationResponse(
            cramp_severity=cramp_severity,
            target_temp_celsius=round(final_temp, 1),
            vibration_mode=VibrationModeEnum.wave,
            vibration_intensity=70,
            duration_minutes=25,
            reasoning="Moderate cramps (severity 5-7). Activating wave vibration modulation (70%) with elevated heat.",
            applied_sensitivity_index=sens,
        )

    else:  # 8 <= cramp_severity <= 10
        raw_temp = 42.0 * sens
        clamped_temp = max(40.0, min(44.0, raw_temp))
        final_temp = min(clamped_temp, MAX_SAFETY_TEMP_CELSIUS)
        return TherapyRecommendationResponse(
            cramp_severity=cramp_severity,
            target_temp_celsius=round(final_temp, 1),
            vibration_mode=VibrationModeEnum.wave,
            vibration_intensity=90,
            duration_minutes=30,
            reasoning="Severe cramps (severity 8-10). Maximizing therapeutic thermal output and high-intensity wave vibration (90%).",
            applied_sensitivity_index=sens,
        )


def adjust_sensitivity_on_feedback(
    current_sensitivity: float,
    feedback_tag: str | FeedbackTagEnum,
) -> Tuple[float, str]:
    """
    Adjusts user sensitivity index based on post-therapy feedback:
    - insufficient_relief: +0.05 (max 1.20)
    - too_hot: -0.08 (min 0.80)
    - just_right: 0.00
    """
    tag_str = str(feedback_tag.value if isinstance(feedback_tag, FeedbackTagEnum) else feedback_tag)

    if tag_str == FeedbackTagEnum.insufficient_relief.value:
        new_sensitivity = min(MAX_SENSITIVITY_INDEX, current_sensitivity + 0.05)
        explanation = f"Increased sensitivity index from {current_sensitivity:.2f} to {new_sensitivity:.2f} (+0.05) to provide deeper thermal relief."
    elif tag_str == FeedbackTagEnum.too_hot.value:
        new_sensitivity = max(MIN_SENSITIVITY_INDEX, current_sensitivity - 0.08)
        explanation = f"Decreased sensitivity index from {current_sensitivity:.2f} to {new_sensitivity:.2f} (-0.08) to prevent heat discomfort."
    else:
        new_sensitivity = current_sensitivity
        explanation = f"Sensitivity index unchanged at {new_sensitivity:.2f} (rated just right)."

    return round(new_sensitivity, 2), explanation
