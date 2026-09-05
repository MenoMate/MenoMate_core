from typing import Optional, Tuple

MAX_POLICY_TEMP_CELSIUS = 44.0
MIN_POLICY_TEMP_CELSIUS = 35.0

MIN_SENSITIVITY_INDEX = 0.80
MAX_SENSITIVITY_INDEX = 1.20


def calculate_therapy_recommendation(
    pain_score: int,
    sensitivity_index: float = 1.0,
) -> dict:
    """
    Deterministic hardware recommendation engine.
    Hardware policy guarantees temperature never exceeds 44.0°C.
    ESP32 wearable remains the final hardware safety authority.
    """
    # Clamp sensitivity index
    sens = max(MIN_SENSITIVITY_INDEX, min(MAX_SENSITIVITY_INDEX, sensitivity_index))
    # Bound pain score
    pain = max(0, min(10, pain_score))

    if pain == 0:
        return {
            "pain_score": 0,
            "target_temperature_c": 0.0,
            "vibration_mode": "off",
            "vibration_intensity": 0,
            "duration_minutes": 0,
            "reasoning": "No pain reported. Thermal and vibration hardware remain idle.",
            "applied_sensitivity_index": sens,
        }
    elif 1 <= pain <= 4:
        raw_temp = 37.0 * sens
        clamped_temp = min(MAX_POLICY_TEMP_CELSIUS, max(35.0, min(38.0, raw_temp)))
        return {
            "pain_score": pain,
            "target_temperature_c": round(clamped_temp, 1),
            "vibration_mode": "pulse",
            "vibration_intensity": 40,
            "duration_minutes": 20,
            "reasoning": "Mild cramps (pain 1-4). Applying gentle pulse vibration (40%) and soothing thermal baseline.",
            "applied_sensitivity_index": sens,
        }
    elif 5 <= pain <= 7:
        raw_temp = 39.5 * sens
        clamped_temp = min(MAX_POLICY_TEMP_CELSIUS, max(38.0, min(41.0, raw_temp)))
        return {
            "pain_score": pain,
            "target_temperature_c": round(clamped_temp, 1),
            "vibration_mode": "wave",
            "vibration_intensity": 70,
            "duration_minutes": 25,
            "reasoning": "Moderate cramps (pain 5-7). Activating wave vibration (70%) with therapeutic heat.",
            "applied_sensitivity_index": sens,
        }
    else:  # 8 - 10
        raw_temp = 42.0 * sens
        clamped_temp = min(MAX_POLICY_TEMP_CELSIUS, max(40.0, min(44.0, raw_temp)))
        return {
            "pain_score": pain,
            "target_temperature_c": round(clamped_temp, 1),
            "vibration_mode": "wave",
            "vibration_intensity": 90,
            "duration_minutes": 30,
            "reasoning": "Severe cramps (pain 8-10). Maximum therapeutic thermal relief and high-intensity wave vibration (90%).",
            "applied_sensitivity_index": sens,
        }


def adjust_sensitivity(
    current_sensitivity: float,
    feedback: Optional[str],
) -> Tuple[float, str]:
    """
    Adjusts user sensitivity index based on post-therapy feedback:
    - insufficient_relief: +0.05 (max 1.20)
    - too_hot: -0.08 (min 0.80)
    - just_right: 0.00
    """
    if not feedback:
        return current_sensitivity, "No feedback provided."

    fb = feedback.lower().strip()
    if fb == "insufficient_relief":
        new_val = min(MAX_SENSITIVITY_INDEX, current_sensitivity + 0.05)
        note = f"Increased sensitivity index to {new_val:.2f} (+0.05) for deeper relief."
    elif fb == "too_hot":
        new_val = max(MIN_SENSITIVITY_INDEX, current_sensitivity - 0.08)
        note = f"Decreased sensitivity index to {new_val:.2f} (-0.08) to prevent heat discomfort."
    else:
        new_val = current_sensitivity
        note = f"Sensitivity index maintained at {new_val:.2f}."

    return round(new_val, 2), note
